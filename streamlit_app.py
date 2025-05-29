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
if 'debug_log' not in st.session_state:
    st.session_state.debug_log = []

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
    
    # Add to debug log instead of showing directly
    add_to_debug_log(f"Quarter {quarter_num + 1} Text:\n{text}\n")
    
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
        
        # Find price - only look for standalone price
        price_line_idx = None
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith('$') and any(c.isdigit() for c in line):
                tag['price'] = line.replace('$', '').strip()
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
                    'Regular Price:' not in line and
                    not line.startswith('$')):
                    product_lines.append(line)
            
            if product_lines:
                # Join all product lines, replacing multiple spaces with single space
                tag['productName'] = ' '.join(' '.join(product_lines).split())
        
        # Ensure all required fields are present, if not, mark them
        required_fields = ['sku', 'productName', 'price', 'barcode']
        missing_fields = []
        for field in required_fields:
            if field not in tag or not tag[field]: # Check if field is missing or empty
                tag[field] = "" # Set to empty string if missing
                if field not in ['barcode']: # Barcode is derived, so don't mark as user-missing if SKU is there
                    missing_fields.append(field)
        
        # If SKU is present but barcode is missing (e.g. from manual add), generate it
        if tag.get('sku') and not tag.get('barcode') and 'barcode' in missing_fields:
            tag['barcode'] = ''.join(filter(str.isalnum, tag['sku']))
            if 'barcode' in missing_fields: # Re-evaluate if barcode is still missing
                 missing_fields.remove('barcode')

        # Special handling if productName is missing but other fields might imply it's an OCR error for a whole tag
        if not tag.get('productName') and not tag.get('sku') and not tag.get('price'):
             # If all key identifiable fields are missing, it's likely not a valid tag segment
             add_to_debug_log(f"Skipping segment due to multiple missing core fields: {lines}")
             return None # Indicate no valid tag found

        tag['_missing_fields'] = missing_fields
        return tag
            
    except Exception as e:
        st.write(f"Error parsing tag: {str(e)}")
        return None

def add_to_debug_log(message):
    """Add message to debug log"""
    st.session_state.debug_log.append(message)

def show_debug_log():
    """Show debug information in expandable section"""
    with st.expander("🔧 Troubleshooting Log"):
        st.write("This section contains technical details useful for troubleshooting:")
        
        # Add download button for log
        log_text = "\n".join(st.session_state.debug_log)
        st.download_button(
            label="Download Log",
            data=log_text,
            file_name="tagger_debug.log",
            mime="text/plain"
        )
        
        # Show log in scrollable area
        st.code(log_text)

def extract_text_from_pdf(pdf_path):
    """Convert PDF to images and extract text from quarters"""
    all_tags = []
    
    try:
        # Convert PDF to images with higher DPI for better OCR
        add_to_debug_log(f"Processing PDF: {pdf_path}")
        images = convert_from_path(
            pdf_path,
            dpi=300,
            fmt='png'
        )
        
        if not images:
            error_msg = "No pages found in PDF"
            add_to_debug_log(f"Error: {error_msg}")
            st.error(error_msg)
            return []
        
        for i, image in enumerate(images):
            add_to_debug_log(f"\nProcessing page {i+1}")
            
            try:
                # Split image into quarters
                quarters = split_image_into_quarters(image)
                
                # Process each quarter
                for j, quarter in enumerate(quarters):
                    try:
                        tag = process_quarter(quarter, j)
                        if tag and all(tag.get(field) for field in ['sku', 'productName', 'price', 'barcode']):
                            all_tags.append(tag)
                            add_to_debug_log(f"Successfully extracted tag: {tag['sku']}")
                        else:
                            add_to_debug_log(f"Skipping invalid tag in page {i+1}, quarter {j+1}")
                    except Exception as e:
                        add_to_debug_log(f"Error processing quarter {j+1} on page {i+1}: {str(e)}")
                        continue
                        
            except Exception as e:
                add_to_debug_log(f"Error processing page {i+1}: {str(e)}")
                continue
                
        if not all_tags:
            error_msg = "No valid tags found in the PDF. Check if the format matches the expected layout."
            add_to_debug_log(f"Error: {error_msg}")
            st.warning(error_msg)
            
    except Exception as e:
        error_msg = f"Error processing PDF: {str(e)}"
        add_to_debug_log(f"Critical Error: {error_msg}")
        st.error(error_msg)
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
            # Ensure price is properly formatted
            price = tag['price'].strip().replace('$', '')
            price_text = f"Price: ${price}"
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
            for idx, tag_data in enumerate(st.session_state.tags):
                missing_fields = tag_data.get('_missing_fields', [])
                
                with st.container():
                    if missing_fields:
                        st.warning(f"Tag {idx + 1} has missing information. Please fill in the fields below.")
                    
                    cols = st.columns([3, 1])
                    
                    with cols[0]:
                        # Product Name
                        current_pn = tag_data.get('productName', '')
                        label_pn = "Product Name"
                        if 'productName' in missing_fields:
                            label_pn += " (REQUIRED)"
                        
                        input_pn = st.text_input(
                            label_pn, 
                            value=current_pn.split('Regular Price:')[0].strip(), 
                            key=f"preview_pn_{idx}"
                        )
                        if input_pn != current_pn.split('Regular Price:')[0].strip():
                            st.session_state.tags[idx]['productName'] = input_pn
                            if input_pn and 'productName' in st.session_state.tags[idx].get('_missing_fields', []):
                                st.session_state.tags[idx]['_missing_fields'].remove('productName')
                            st.rerun()

                        # SKU
                        current_sku = tag_data.get('sku', '')
                        label_sku = "SKU"
                        if 'sku' in missing_fields:
                            label_sku += " (REQUIRED)"
                        
                        input_sku = st.text_input(
                            label_sku, 
                            value=current_sku, 
                            key=f"preview_sku_{idx}"
                        )
                        if input_sku != current_sku:
                            st.session_state.tags[idx]['sku'] = input_sku
                            # If SKU is updated, regenerate barcode and check missing status
                            if input_sku:
                                new_barcode = ''.join(filter(str.isalnum, input_sku))
                                st.session_state.tags[idx]['barcode'] = new_barcode
                                if 'sku' in st.session_state.tags[idx].get('_missing_fields', []):
                                    st.session_state.tags[idx]['_missing_fields'].remove('sku')
                                if new_barcode and 'barcode' in st.session_state.tags[idx].get('_missing_fields', []):
                                     st.session_state.tags[idx]['_missing_fields'].remove('barcode')
                            elif 'sku' not in st.session_state.tags[idx].get('_missing_fields', []):
                                st.session_state.tags[idx].get('_missing_fields', []).append('sku') # SKUid removed, mark as missing
                            st.rerun()

                    with cols[1]:
                        # Price
                        current_price = tag_data.get('price', '')
                        label_price = "Price"
                        if 'price' in missing_fields:
                            label_price += " (REQUIRED)"
                        
                        input_price = st.text_input(
                            label_price, 
                            value=current_price, 
                            key=f"preview_price_{idx}",
                            help="Enter price without $ symbol"
                        )
                        if input_price != current_price:
                            processed_price = input_price.replace('$', '').strip()
                            st.session_state.tags[idx]['price'] = processed_price
                            if processed_price and 'price' in st.session_state.tags[idx].get('_missing_fields', []):
                                st.session_state.tags[idx]['_missing_fields'].remove('price')
                            elif not processed_price and 'price' not in st.session_state.tags[idx].get('_missing_fields', []):
                                st.session_state.tags[idx].get('_missing_fields', []).append('price')
                            st.rerun()
                
                # Add a separator after each tag preview, except for the last one
                if idx < len(st.session_state.tags) - 1:
                    st.markdown("---")
            
            # Show generate button
            st.markdown("---")
            
            all_tags_valid = True
            if st.session_state.tags: # Ensure tags exist before checking
                for tag_check in st.session_state.tags:
                    if tag_check.get('_missing_fields', []):
                        all_tags_valid = False
                        break
            # If st.session_state.tags is empty, all_tags_valid remains True, generate_pdf should handle empty list.

            if all_tags_valid:
                if st.button("Generate PDF", type="primary", key="generate_pdf_button_main"):
                    pdf = generate_pdf() # generate_pdf() should handle empty st.session_state.tags
                    if pdf:
                        st.download_button(
                            label="Download PDF",
                            data=pdf,
                            file_name="price_tags.pdf",
                            mime="application/pdf",
                            key="download_pdf_button_main"
                        )
                    else:
                        st.error("PDF generation failed or resulted in an empty document.")
            else:
                st.error("Please resolve all (REQUIRED) fields in the tags above before generating the PDF.")
                # Show a disabled button for UX consistency
                st.button("Generate PDF", type="primary", disabled=True, key="generate_pdf_button_disabled_main")
            
            # Show debug log at the bottom
            show_debug_log()
                
        else:
            st.error("No valid tags found. Please check if the PDF format is correct.")
            st.session_state.tags = []
            show_debug_log()  # Show debug log even if no tags found
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        st.session_state.tags = []
        show_debug_log()  # Show debug log even if no tags found
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
        # Clean up product name in expander title
        product_name = tag.get('productName', 'Unnamed Tag').split('Regular Price:')[0].strip()
        missing_fields = tag.get('_missing_fields', [])
        expander_title = product_name if product_name else "Tag (Missing Name)"
        if not product_name and not tag.get('sku') and not tag.get('price'): # Likely an empty/failed OCR tag
            expander_title = f"Tag {idx + 1} (Empty - Needs Review)"
        elif missing_fields:
            expander_title += " ⚠️ (NEEDS ATTENTION)"

        with st.expander(expander_title):
            if missing_fields:
                st.warning("This tag has missing required information. Please fill in all (REQUIRED) fields below.")

            cols = st.columns([2, 1])
            
            with cols[0]:
                # Editable fields for Product Name, SKU, and Price
                # Editable Product Name
                label_pn = "Product Name"
                if 'productName' in missing_fields:
                    label_pn += " (REQUIRED)"
                new_product_name = st.text_input(
                    label_pn,
                    value=tag.get('productName', ''),
                    key=f"product_name_edit_{idx}"
                )

                # Editable SKU
                label_sku = "SKU"
                if 'sku' in missing_fields:
                    label_sku += " (REQUIRED)"
                new_sku = st.text_input(
                    label_sku,
                    value=tag.get('sku', ''),
                    key=f"sku_edit_{idx}"
                )
                st.write(f"Barcode: {tag['barcode']}")
                if tag.get('description'):
                    st.write(f"Description: {tag['description']}")

            
            with cols[1]:
                # Price editing
                # Editable Price
                label_price = "Price"
                if 'price' in missing_fields:
                    label_price += " (REQUIRED)"
                new_price = st.text_input(
                    label_price,
                    value=tag.get('price', ''),
                    key=f"price_edit_{idx}",
                    help="Enter new price without $ symbol"
                )
                
                # Update and Remove buttons side by side
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_{idx}"):
                        try:
                            # Validate price format
                            new_price = new_price.strip()
                            # Remove any existing $ symbol
                            new_price = new_price.replace('$', '')
                            # Ensure it's a valid number
                            float(new_price)  # This will raise ValueError if not a valid number
                            # Process and validate price
                            processed_price = new_price.replace('$', '').strip()
                            float(processed_price) # Validate if it's a number, will raise ValueError if not

                            # Update fields in session state
                            st.session_state.tags[idx]['productName'] = new_product_name
                            st.session_state.tags[idx]['sku'] = new_sku
                            st.session_state.tags[idx]['price'] = processed_price

                            # Update missing fields list
                            current_missing = list(st.session_state.tags[idx].get('_missing_fields', []))
                            
                            # Product Name
                            if new_product_name and 'productName' in current_missing:
                                current_missing.remove('productName')
                            elif not new_product_name and 'productName' not in current_missing:
                                current_missing.append('productName')
                            
                            # SKU & Barcode
                            if new_sku and 'sku' in current_missing:
                                current_missing.remove('sku')
                            elif not new_sku and 'sku' not in current_missing:
                                current_missing.append('sku')
                            
                            # Barcode depends on SKU
                            if new_sku:
                                new_barcode_val = ''.join(filter(str.isalnum, new_sku))
                                st.session_state.tags[idx]['barcode'] = new_barcode_val
                                if new_barcode_val and 'barcode' in current_missing:
                                    current_missing.remove('barcode')
                                elif not new_barcode_val and 'barcode' not in current_missing:
                                    current_missing.append('barcode') # Should not happen if SKU is present
                            else: # SKU is empty
                                st.session_state.tags[idx]['barcode'] = ""
                                if 'barcode' not in current_missing:
                                    current_missing.append('barcode')

                            # Price
                            if processed_price and 'price' in current_missing:
                                current_missing.remove('price')
                            elif not processed_price and 'price' not in current_missing:
                                current_missing.append('price')

                            st.session_state.tags[idx]['_missing_fields'] = current_missing
                            
                            st.success(f"Tag updated!")
                            st.rerun()
                        except ValueError:
                            st.error("Please enter a valid price (numbers only)")
                with col2:
                    if st.button("Remove", key=f"remove_{idx}"):
                        st.session_state.tags.pop(idx)
                        st.rerun()
