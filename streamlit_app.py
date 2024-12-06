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

st.set_page_config(page_title="Price Tag Generator", layout="wide")

st.title("Price Tag Generator ")

# Initialize session state
if 'tags' not in st.session_state:
    st.session_state.tags = []
if 'uploaded_pdf_text' not in st.session_state:
    st.session_state.uploaded_pdf_text = None

def split_image_and_extract_text(image):
    """Split the image down the middle and extract text from both halves"""
    width, height = image.size
    mid_point = width // 2
    
    # Split into left and right halves
    left_half = image.crop((0, 0, mid_point, height))
    right_half = image.crop((mid_point, 0, width, height))
    
    # Extract text from each half
    custom_config = r'--oem 3 --psm 6'
    left_text = pytesseract.image_to_string(left_half, config=custom_config)
    right_text = pytesseract.image_to_string(right_half, config=custom_config)
    
    # Debug: Show the split images
    col1, col2 = st.columns(2)
    with col1:
        st.write("Left Half:")
        st.image(left_half)
    with col2:
        st.write("Right Half:")
        st.image(right_half)
    
    return left_text, right_text

def parse_half_page(text):
    """Parse text from one half of the page"""
    tags = []
    lines = text.split('\n')
    i = 0
    
    while i < len(lines):
        try:
            line = lines[i].strip()
            
            if 'Model #:' in line:
                # Get category from previous lines
                category = "Hearth"
                for j in range(i-1, max(0, i-3), -1):
                    if 'Hearth >' in lines[j]:
                        category = lines[j].strip()
                        break
                
                # Get model number
                sku = line.replace('Model #:', '').strip()
                
                # Get product name from next line
                product_name = lines[i+1].strip() if i+1 < len(lines) else ""
                
                # Get price from next lines
                price = ""
                for j in range(i+1, min(len(lines), i+4)):
                    if 'Regular Price: $' in lines[j]:
                        price = lines[j].replace('Regular Price: $', '').strip()
                        break
                
                if sku and price and product_name:
                    tags.append({
                        "sku": sku,
                        "productName": product_name,
                        "price": price,
                        "barcode": ''.join(filter(str.isalnum, sku)),
                        "description": category
                    })
            i += 1
            
        except Exception as e:
            st.write(f"Error processing line {i}: {str(e)}")
            i += 1
            continue
    
    return tags

def extract_text_from_pdf(pdf_path):
    """Convert PDF to images and extract text from both halves"""
    all_tags = []
    
    # Convert PDF to images with higher DPI for better OCR
    images = convert_from_path(
        pdf_path,
        dpi=300,
        fmt='png'
    )
    
    for i, image in enumerate(images):
        st.write(f"\nProcessing page {i+1}")
        
        # Split image and get text from both halves
        left_text, right_text = split_image_and_extract_text(image)
        
        # Debug: Show extracted text
        st.write("\nLeft half text:")
        st.code(left_text)
        st.write("\nRight half text:")
        st.code(right_text)
        
        # Parse each half separately
        left_tags = parse_half_page(left_text)
        right_tags = parse_half_page(right_text)
        
        # Add all tags to the list
        all_tags.extend(left_tags)
        all_tags.extend(right_tags)
    
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
        tags = extract_text_from_pdf(tmp_file_path)
        
        st.write(f"\nTotal tags found: {len(tags)}")
        for tag in tags:
            st.write(f"\nFound product:")
            st.write(f"- Name: {tag['productName']}")
            st.write(f"- SKU: {tag['sku']}")
            st.write(f"- Price: ${tag['price']}")
            st.write(f"- Category: {tag['description']}")
        
        if tags:
            st.session_state.tags = tags
            st.success(f"Successfully extracted {len(tags)} tags!")
        else:
            st.warning("No tags found in the PDF. Check the format and try again.")
        
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
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
    size = [float(x) for x in tag_size.split('x')]
    
    c = canvas.Canvas(buffer, pagesize=(size[0]*inch, size[1]*inch))
    
    for tag in st.session_state.tags:
        # Set font for product name
        c.setFont(font_name, font_size)
        
        # Draw product name
        c.drawString(margin*inch, 
                    (size[1] - margin)*inch, 
                    tag['productName'])
        
        # Draw price (larger font)
        c.setFont(font_name, price_size)
        c.drawString(margin*inch,
                    (size[1] - 0.5)*inch,
                    f"${tag['price']}")
        
        # Draw SKU
        c.setFont(font_name, font_size)
        c.drawString(margin*inch,
                    0.4*inch,
                    f"SKU: {tag['sku']}")
        
        # Generate and draw barcode
        barcode = code128.Code128(tag['barcode'])
        barcode.drawOn(c, margin*inch, 0.1*inch)
        
        c.showPage()
    
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
