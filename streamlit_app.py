import streamlit as st
import json
import io
import tempfile
import os
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract
import re
from PIL import Image
import numpy as np

st.set_page_config(page_title="Price Tag Generator", layout="wide")
st.title("Price Tag Generator ")

# Initialize session state
if 'tags' not in st.session_state:
    st.session_state.tags = []
if 'uploaded_pdf_text' not in st.session_state:
    st.session_state.uploaded_pdf_text = None
if 'tag_exceptions' not in st.session_state:
    st.session_state.tag_exceptions = {}
if 'resolved_tags' not in st.session_state:
    st.session_state.resolved_tags = {}

def split_image_into_quarters(image):
    """Split the image into four equal quarters"""
    width, height = image.size
    mid_w = width // 2
    mid_h = height // 2
    
    # Split into quarters
    quarters = [
        # Top left
        image.crop((0, 0, mid_w, mid_h)),
        # Top right
        image.crop((mid_w, 0, width, mid_h)),
        # Bottom left
        image.crop((0, mid_h, mid_w, height)),
        # Bottom right
        image.crop((mid_w, mid_h, width, height))
    ]
    
    return quarters

def process_quarter(image, quarter_num):
    """Process a single quarter of the page"""
    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Extract text with custom configuration
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(image, config=custom_config)
    
    # Debug: Show the quarter and its text
    st.write(f"\nQuarter {quarter_num + 1}:")
    st.image(image, width=300)
    st.code(text)
    
    # Parse the text for this quarter
    tag = parse_single_tag(text)
    return tag

def parse_single_tag(text):
    """Parse text from a single tag"""
    try:
        lines = text.split('\n')
        tag = {}
        
        # Find category (Hearth > XXX)
        for line in lines:
            if 'Hearth >' in line:
                tag['description'] = line.strip()
                break
        
        # Find Model number
        for line in lines:
            if 'Model #:' in line:
                sku = line.replace('Model #:', '').strip()
                tag['sku'] = sku
                tag['barcode'] = ''.join(filter(str.isalnum, sku))
                break
        
        # Find price
        for line in lines:
            if 'Regular Price: $' in line:
                price = line.replace('Regular Price: $', '').strip()
                tag['price'] = price
                break
        
        # Find product name (usually between Model # and Regular Price)
        try:
            model_idx = next(i for i, line in enumerate(lines) if 'Model #:' in line)
            price_idx = next(i for i, line in enumerate(lines) if 'Regular Price:' in line)
            
            # Get all lines between model and price
            name_lines = [line.strip() for line in lines[model_idx+1:price_idx] if line.strip()]
            if name_lines:
                tag['productName'] = ' '.join(name_lines)
        except:
            # Fallback: look for any substantial line that's not category/model/price
            for line in lines:
                if (len(line.strip()) > 10 and 
                    'Hearth >' not in line and 
                    'Model #:' not in line and 
                    'Regular Price:' not in line):
                    tag['productName'] = line.strip()
                    break
        
        # Validate tag has all required fields
        required_fields = ['sku', 'productName', 'price', 'barcode']
        if all(field in tag for field in required_fields):
            return tag
        else:
            missing = [field for field in required_fields if field not in tag]
            st.write(f"Missing fields in tag: {missing}")
            return None
            
    except Exception as e:
        st.write(f"Error parsing tag: {str(e)}")
        return None

def extract_text_from_pdf(pdf_path):
    """Convert PDF to images and extract text from quarters"""
    all_tags = []
    
    try:
        # Convert PDF to images with higher DPI for better OCR
        images = convert_from_path(
            pdf_path,
            dpi=300,
            fmt='png'
        )
        
        if not images:
            st.error("No pages found in PDF")
            return []
        
        for i, image in enumerate(images):
            st.write(f"\nProcessing page {i+1}")
            
            try:
                # Split image into quarters
                quarters = split_image_into_quarters(image)
                
                # Process each quarter
                for j, quarter in enumerate(quarters):
                    try:
                        tag = process_quarter(quarter, j)
                        if tag and all(tag.get(field) for field in ['sku', 'productName', 'price', 'barcode']):
                            all_tags.append(tag)
                        else:
                            st.warning(f"Skipping invalid tag in page {i+1}, quarter {j+1}")
                    except Exception as e:
                        st.warning(f"Error processing quarter {j+1} on page {i+1}: {str(e)}")
                        continue
                        
            except Exception as e:
                st.warning(f"Error processing page {i+1}: {str(e)}")
                continue
                
        if not all_tags:
            st.warning("No valid tags found in the PDF. Check if the format matches the expected layout.")
            
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return []
        
    return all_tags

def validate_tag_text(text, max_width, font_name='Helvetica-Bold', font_size=12):
    """Calculate if text will fit within max_width"""
    from reportlab.pdfbase import pdfmetrics
    
    # Get the width of the text
    text_width = pdfmetrics.stringWidth(text, font_name, font_size)
    # Allow more generous threshold - about 45 characters for typical text
    return text_width <= max_width * 1.5  # Increased tolerance to 50%

def validate_tags(tags):
    """Check all tags for potential issues"""
    exceptions = {}
    max_width = 3.6 * inch  # 4 inch tag width minus margins
    
    for i, tag in enumerate(tags):
        tag_issues = []
        
        # Check product name length
        text = tag['productName'].upper()
        from reportlab.pdfbase import pdfmetrics
        text_width = pdfmetrics.stringWidth(text, 'Helvetica-Bold', 12)
        if text_width > max_width * 1.5:  # Using same tolerance as validate_tag_text
            tag_issues.append({
                'type': 'text_overflow',
                'field': 'productName',
                'content': text,
                'message': f'Product name is {int((text_width/max_width)*100)}% of available width',
                'width_ratio': text_width/max_width
            })
        
        if tag_issues:
            exceptions[i] = {
                'tag': tag,
                'issues': tag_issues
            }
    
    return exceptions

def handle_tag_exceptions():
    """UI for handling tag exceptions"""
    if not st.session_state.tag_exceptions:
        return True
    
    st.warning(f"Found {len(st.session_state.tag_exceptions)} tags that may need attention")
    
    with st.expander("🔧 Review and Edit Long Product Names", expanded=True):
        st.write("The following product names may be too long for optimal display. Edit if needed:")
        
        for idx, exception in st.session_state.tag_exceptions.items():
            tag = exception['tag']
            issues = exception['issues']
            
            st.markdown("---")
            cols = st.columns([3, 1])
            with cols[0]:
                st.write(f"**SKU:** {tag['sku']}")
                
                # Show length warning with color
                for issue in issues:
                    if issue['type'] == 'text_overflow':
                        ratio = issue['width_ratio']
                        color = "red" if ratio > 1.5 else "orange" if ratio > 1.2 else "yellow"
                        st.markdown(f"<p style='color: {color}'>{issue['message']}</p>", unsafe_allow_html=True)
                
                new_text = st.text_input(
                    "Edit product name if needed:",
                    value=tag['productName'],
                    key=f"fix_{idx}"
                )
                
                # Show live preview of text width
                if new_text:
                    from reportlab.pdfbase import pdfmetrics
                    new_width = pdfmetrics.stringWidth(new_text.upper(), 'Helvetica-Bold', 12)
                    ratio = new_width / (3.6 * inch)
                    color = "red" if ratio > 1.5 else "orange" if ratio > 1.2 else "green"
                    st.markdown(f"<p style='color: {color}'>Current width: {int(ratio*100)}% of available space</p>", unsafe_allow_html=True)
            
            with cols[1]:
                st.write(f"**Price:** ${tag['price']}")
                if st.button(f"Save Changes", key=f"save_{idx}"):
                    if new_text != tag['productName']:
                        # Validate the new text
                        if validate_tag_text(new_text.upper(), 3.6 * inch):
                            st.session_state.resolved_tags[idx] = {
                                **tag,
                                'productName': new_text
                            }
                            st.success("Updated! Text fits within limits.")
                        else:
                            st.error("Text is still too long! Try making it shorter.")
                            
        st.markdown("---")
        if st.session_state.resolved_tags:
            if st.button("Continue with Changes", type="primary"):
                # Update the original tags with resolved ones
                for idx, resolved_tag in st.session_state.resolved_tags.items():
                    st.session_state.tags[idx] = resolved_tag
                st.session_state.tag_exceptions = {}
                st.session_state.resolved_tags = {}
                return True
        
        if st.button("Continue without Changes", type="secondary"):
            st.session_state.tag_exceptions = {}
            return True
    
    return False

# File upload section
st.header("Upload Source PDF")
uploaded_file = st.file_uploader("Choose a PDF file", type=['pdf'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name
    
    try:
        # Process the PDF and get tags
        st.write("Processing PDF pages...")
        tags = extract_text_from_pdf(tmp_file_path)
        
        if tags:
            st.success(f"Found {len(tags)} valid tags!")
            st.session_state.tags = tags
            
            # Validate tags
            st.session_state.tag_exceptions = validate_tags(tags)
            
            # Show tag preview
            st.subheader("Preview of Extracted Tags")
            for idx, tag in enumerate(tags):
                with st.container():
                    cols = st.columns([2, 1, 1])
                    with cols[0]:
                        st.write(f"**{tag['productName']}**")
                    with cols[1]:
                        st.write(f"SKU: {tag['sku']}")
                    with cols[2]:
                        st.write(f"Price: ${tag['price']}")
            
            # Handle exceptions if any
            if st.session_state.tag_exceptions:
                st.warning(f"Found {len(st.session_state.tag_exceptions)} tags that may need attention")
                
                st.subheader("🔧 Review and Edit Long Product Names")
                st.write("The following product names may be too long for optimal display. Edit if needed:")
                
                for idx, exception in st.session_state.tag_exceptions.items():
                    tag = exception['tag']
                    issues = exception['issues']
                    
                    st.markdown("---")
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.write(f"**SKU:** {tag['sku']}")
                        
                        # Show length warning with color
                        for issue in issues:
                            if issue['type'] == 'text_overflow':
                                ratio = issue['width_ratio']
                                color = "red" if ratio > 1.5 else "orange" if ratio > 1.2 else "yellow"
                                st.markdown(f"<p style='color: {color}'>{issue['message']}</p>", unsafe_allow_html=True)
                        
                        new_text = st.text_input(
                            "Edit product name if needed:",
                            value=tag['productName'],
                            key=f"fix_{idx}"
                        )
                        
                        # Show live preview of text width
                        if new_text:
                            from reportlab.pdfbase import pdfmetrics
                            new_width = pdfmetrics.stringWidth(new_text.upper(), 'Helvetica-Bold', 12)
                            ratio = new_width / (3.6 * inch)
                            color = "red" if ratio > 1.5 else "orange" if ratio > 1.2 else "green"
                            st.markdown(f"<p style='color: {color}'>Current width: {int(ratio*100)}% of available space</p>", unsafe_allow_html=True)
                    
                    with cols[1]:
                        st.write(f"**Price:** ${tag['price']}")
                        if st.button(f"Save Changes", key=f"save_{idx}"):
                            if new_text != tag['productName']:
                                # Validate the new text
                                if validate_tag_text(new_text.upper(), 3.6 * inch):
                                    st.session_state.resolved_tags[idx] = {
                                        **tag,
                                        'productName': new_text
                                    }
                                    st.success("Updated! Text fits within limits.")
                                else:
                                    st.error("Text is still too long! Try making it shorter.")
                
                st.markdown("---")
                cols = st.columns([1, 1])
                with cols[0]:
                    if st.session_state.resolved_tags and st.button("Continue with Changes", type="primary"):
                        # Update the original tags with resolved ones
                        for idx, resolved_tag in st.session_state.resolved_tags.items():
                            st.session_state.tags[idx] = resolved_tag
                        st.session_state.tag_exceptions = {}
                        st.session_state.resolved_tags = {}
                        st.rerun()
                
                with cols[1]:
                    if st.button("Continue without Changes", type="secondary"):
                        st.session_state.tag_exceptions = {}
                        st.session_state.resolved_tags = {}
                        st.rerun()
            
            # Show generate button only if no exceptions or they've been handled
            if not st.session_state.tag_exceptions:
                st.markdown("---")
                if st.button("Generate PDF", type="primary"):
                    pdf = generate_pdf()
                    st.download_button(
                        label="Download PDF",
                        data=pdf,
                        file_name="price_tags.pdf",
                        mime="application/pdf"
                    )
                    
        else:
            st.error("No valid tags found. Please check if the PDF format is correct.")
            st.session_state.tags = []
            st.session_state.tag_exceptions = {}
            st.session_state.resolved_tags = {}
        
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        st.session_state.tags = []
        st.session_state.tag_exceptions = {}
        st.session_state.resolved_tags = {}
    finally:
        # Cleanup
        try:
            os.unlink(tmp_file_path)
        except:
            pass

# Sidebar for settings
with st.sidebar:
    st.header("Tag Settings")
    tag_size = st.selectbox("Tag Size", ["4x1.5"], help="Size in inches (width x height)")
    
    st.subheader("Font Settings")
    font_name = st.selectbox("Font", ["Helvetica"], help="Select font family")
    font_size = st.number_input("Base Font Size", min_value=8, max_value=24, value=12)
    price_size = st.number_input("Price Font Size", min_value=8, max_value=36, value=14)
    margin = st.number_input("Margin (inches)", min_value=0.1, max_value=0.5, value=0.25, step=0.05)

# Main content
st.header("Product Information")

# Form for adding new tags
with st.form("new_tag"):
    st.subheader("Add New Tag")
    col1, col2 = st.columns(2)
    
    with col1:
        product_name = st.text_input("Product Name")
        price = st.text_input("Price")
    
    with col2:
        sku = st.text_input("SKU")
        barcode = st.text_input("Barcode")
    
    description = st.text_area("Description (optional)")
    
    submitted = st.form_submit_button("Add Tag")
    if submitted and product_name and price and sku and barcode:
        new_tag = {
            "productName": product_name,
            "price": price,
            "sku": sku,
            "barcode": barcode,
            "description": description
        }
        st.session_state.tags.append(new_tag)
        st.success("Tag added successfully!")

# Display and manage existing tags
if st.session_state.tags:
    st.subheader("Current Tags")
    for idx, tag in enumerate(st.session_state.tags):
        with st.expander(f"{tag['productName']} - ${tag['price']}"):
            st.write(f"SKU: {tag['sku']}")
            st.write(f"Barcode: {tag['barcode']}")
            if tag['description']:
                st.write(f"Description: {tag['description']}")
            if st.button(f"Remove Tag {idx}"):
                st.session_state.tags.pop(idx)
                st.rerun()

def generate_pdf():
    buffer = io.BytesIO()
    page_width = 8.5 * inch
    page_height = 11 * inch
    tag_width = 4 * inch
    tag_height = 1.5 * inch
    
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    
    # Calculate starting positions
    left_margin = (page_width - tag_width) / 2
    top_margin = page_height - inch
    
    # Process tags in groups of 6
    for i in range(0, len(st.session_state.tags), 6):
        group = st.session_state.tags[i:i+6]
        y_position = top_margin
        
        for tag in group:
            # Draw blue bar at bottom of tag
            c.setFillColorRGB(0, 0.3, 0.8)  # Dark blue
            c.rect(left_margin, y_position - tag_height + 0.1*inch, 
                  tag_width, 0.2*inch, fill=1)
            c.setFillColorRGB(0, 0, 0)  # Back to black
            
            # Draw tag border
            c.setLineWidth(1)
            c.rect(left_margin, y_position - tag_height, tag_width, tag_height)
            
            # Handle multi-line product names
            c.setFont('Helvetica-Bold', 12)
            lines = tag['productName'].upper().split('\n')
            
            # Calculate total height needed for text
            line_height = 14 / 72  # 14pt in inches
            total_height = line_height * len(lines)
            start_y = y_position - 0.45*inch
            
            # Draw each line centered
            for line in lines:
                text_width = c.stringWidth(line, 'Helvetica-Bold', 12)
                x = left_margin + (tag_width - text_width) / 2
                c.drawString(x, start_y, line)
                start_y -= line_height * inch
            
            # Draw model number in italics, centered
            c.setFont('Helvetica-Oblique', 10)
            model_text = f"Model: {tag['sku']}"
            text_width = c.stringWidth(model_text, 'Helvetica-Oblique', 10)
            x = left_margin + (tag_width - text_width) / 2
            c.drawString(x, y_position - 0.8*inch, model_text)
            
            # Draw price (large and bold), centered
            c.setFont('Helvetica-Bold', 14)
            price_text = f"Price: ${tag['price']}"
            text_width = c.stringWidth(price_text, 'Helvetica-Bold', 14)
            x = left_margin + (tag_width - text_width) / 2
            c.drawString(x, y_position - 1.1*inch, price_text)
            
            # Move to next tag position
            y_position -= tag_height + 0.2*inch
        
        # Start new page if we have more tags
        if i + 6 < len(st.session_state.tags):
            c.showPage()
            c.setFont('Helvetica', 12)
    
    c.save()
    buffer.seek(0)
    return buffer

# Generate PDF button
if st.session_state.tags:
    if st.button("Generate PDF"):
        pdf = generate_pdf()
        st.download_button(
            label="Download PDF",
            data=pdf,
            file_name="price_tags.pdf",
            mime="application/pdf"
        )
else:
    st.info("Add some tags to generate a PDF")
