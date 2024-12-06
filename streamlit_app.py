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
    
    # Convert PDF to images with higher DPI for better OCR
    images = convert_from_path(
        pdf_path,
        dpi=300,
        fmt='png'
    )
    
    for i, image in enumerate(images):
        st.write(f"\nProcessing page {i+1}")
        
        # Split image into quarters
        quarters = split_image_into_quarters(image)
        
        # Process each quarter
        for j, quarter in enumerate(quarters):
            tag = process_quarter(quarter, j)
            if tag:
                all_tags.append(tag)
    
    return all_tags

# File upload section
st.header("Upload Source PDF")
uploaded_file = st.file_uploader("Choose a PDF file", type=['pdf'])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name
    
    try:
        # Process the PDF and get tags
        with st.expander("🔍 Processing Details", expanded=False):
            st.write("Processing PDF pages...")
            tags = extract_text_from_pdf(tmp_file_path)
            st.write(f"\nTotal tags found: {len(tags)}")
        
        with st.expander("📋 Found Products", expanded=False):
            for tag in tags:
                st.write("---")
                st.write(f"**Product:** {tag['productName']}")
                cols = st.columns(2)
                with cols[0]:
                    st.write(f"SKU: {tag['sku']}")
                with cols[1]:
                    st.write(f"Price: ${tag['price']}")
                if 'description' in tag:
                    st.write(f"Category: {tag['description']}")
        
        if tags:
            st.session_state.tags = tags
            st.success(f"✅ Successfully extracted {len(tags)} tags!")
        else:
            st.warning("⚠️ No tags found in the PDF. Check the format and try again.")
        
    except Exception as e:
        st.error(f"❌ Error processing PDF: {str(e)}")
    finally:
        # Cleanup
        os.unlink(tmp_file_path)

# Sidebar for settings
with st.sidebar:
    st.header("Tag Settings")
    tag_size = st.selectbox("Tag Size", ["4x1.5"], help="Size in inches (width x height)")
    
    st.subheader("Font Settings")
    font_name = st.selectbox("Font", ["Helvetica"], help="Select font family")
    font_size = st.number_input("Base Font Size", min_value=8, max_value=24, value=12)
    price_size = st.number_input("Price Font Size", min_value=8, max_value=36, value=16)
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
    # Use letter size paper
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
            c.setLineWidth(1)  # 1 point line width
            c.rect(left_margin, y_position - tag_height, tag_width, tag_height)
            
            # Draw product name in bold, centered
            c.setFont('Helvetica-Bold', 12)
            product_name = tag['productName'].upper()
            text_width = c.stringWidth(product_name, 'Helvetica-Bold', 12)
            x = left_margin + (tag_width - text_width) / 2
            c.drawString(x, y_position - 0.3*inch, product_name)
            
            # Draw model number in italics, centered
            c.setFont('Helvetica-Oblique', 10)
            model_text = f"Model: {tag['sku']}"
            text_width = c.stringWidth(model_text, 'Helvetica-Oblique', 10)
            x = left_margin + (tag_width - text_width) / 2
            c.drawString(x, y_position - 0.6*inch, model_text)
            
            # Draw price (large and bold), centered
            c.setFont('Helvetica-Bold', 14)
            price_text = f"Price: ${tag['price']}"
            text_width = c.stringWidth(price_text, 'Helvetica-Bold', 14)
            x = left_margin + (tag_width - text_width) / 2
            c.drawString(x, y_position - 0.9*inch, price_text)
            
            # Move to next tag position
            y_position -= tag_height + 0.2*inch  # 0.2 inch gap between tags
        
        # Start new page if we have more tags
        if i + 6 < len(st.session_state.tags):
            c.showPage()
            c.setFont('Helvetica', 12)  # Reset font for new page
    
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
