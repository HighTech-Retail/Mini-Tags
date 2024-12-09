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
        model_line_idx = None
        for i, line in enumerate(lines):
            if 'Model #:' in line:
                sku = line.replace('Model #:', '').strip()
                tag['sku'] = sku
                tag['barcode'] = ''.join(filter(str.isalnum, sku))
                model_line_idx = i
                break
        
        # Find price - look for both formats
        price_line_idx = None
        for i, line in enumerate(lines):
            if 'Regular Price: $' in line:
                price = line.replace('Regular Price: $', '').strip()
                tag['price'] = price
                price_line_idx = i
                break
            elif line.strip().startswith('$') and any(c.isdigit() for c in line):
                tag['price'] = line.strip().replace('$', '')
                price_line_idx = i
                break
        
        # Find product name - combine all relevant lines between model and price
        if model_line_idx is not None and price_line_idx is not None:
            product_lines = []
            for line in lines[model_line_idx + 1:price_line_idx]:
                line = line.strip()
                if (len(line) > 0 and 
                    'Hearth >' not in line and
                    'Contracts Available' not in line and
                    'Fireplace Distributors' not in line and
                    not line.startswith('$')):
                    product_lines.append(line)
            
            if product_lines:
                # Join all product lines, replacing multiple spaces with single space
                tag['productName'] = ' '.join(' '.join(product_lines).split())
        
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
    
    # Split text into lines if it contains the separator
    lines = text.split('|')
    
    # Check each line separately
    for i, line in enumerate(lines):
        text_width = pdfmetrics.stringWidth(line.strip().upper(), font_name, font_size)
        # First line can be longer than second line
        max_allowed = max_width * (1.5 if i == 0 else 1.2)
        if text_width > max_allowed:
            return False
    return True

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

def auto_split_text(text, max_width, c, initial_font_size=12):
    """Automatically split and size text to fit within max_width"""
    from reportlab.pdfbase import pdfmetrics
    
    text = text.upper()
    
    # Function to check if text fits
    def text_fits(text, font_size, max_width_ratio=1.5):
        return pdfmetrics.stringWidth(text, 'Helvetica-Bold', font_size) <= max_width * max_width_ratio
    
    # Try to find natural split points
    split_candidates = [
        # Split before "BAGGED" or "FLAT"
        lambda t: t.find(", BAGGED"),
        lambda t: t.find(", FLAT"),
        # Split before parentheses
        lambda t: t.find(" ("),
        # Split after measurements (before descriptive text)
        lambda t: next((i for i, c in enumerate(t) if c.isalpha() and 
                       i > 0 and (t[i-1].isdigit() or t[i-1] in 'X/')), -1),
        # Split at comma
        lambda t: t.find(","),
        # Split at last space in first half
        lambda t: t.rfind(" ", 0, len(t)//2 + 10)
    ]
    
    # Try each split point with original font size
    font_size = initial_font_size
    for get_split_point in split_candidates:
        split_point = get_split_point(text)
        if split_point > 0:
            line1 = text[:split_point].strip()
            line2 = text[split_point:].strip(" ,()")
            
            if text_fits(line1, font_size, 1.5) and text_fits(line2, font_size, 1.2):
                return [line1, line2], font_size
    
    # If no good split point found, try reducing font size
    while font_size >= 9:
        # Try splitting at the middle
        mid_point = len(text) // 2
        split_point = text.rfind(" ", 0, mid_point + 10)
        if split_point > 0:
            line1 = text[:split_point].strip()
            line2 = text[split_point:].strip()
            if text_fits(line1, font_size, 1.5) and text_fits(line2, font_size, 1.2):
                return [line1, line2], font_size
        font_size -= 1
    
    # Last resort: force split at midpoint with smallest font
    mid_point = len(text) // 2
    split_point = text.rfind(" ", 0, mid_point + 10)
    if split_point > 0:
        return [text[:split_point].strip(), text[split_point:].strip()], 9
    
    return [text], 9

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
            
            # Auto-split and size product name
            lines, font_size = auto_split_text(tag['productName'], 3.6 * inch, c)
            
            # Draw product name
            c.setFont('Helvetica-Bold', font_size)
            
            # Calculate vertical spacing based on number of lines
            if len(lines) == 1:
                start_y = y_position - 0.45*inch
                line_spacing = 0
            else:
                start_y = y_position - 0.35*inch  # Start higher for two lines
                line_spacing = 0.15 * inch
            
            # Draw each line centered
            for i, line in enumerate(lines):
                text_width = c.stringWidth(line, 'Helvetica-Bold', font_size)
                x = left_margin + (tag_width - text_width) / 2
                c.drawString(x, start_y - (i * line_spacing), line)
            
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
            
            # Show generate button
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
