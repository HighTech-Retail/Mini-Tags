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

st.set_page_config(page_title="Price Tag Generator", layout="wide")

st.title("Price Tag Generator ")

# Initialize session state
if 'tags' not in st.session_state:
    st.session_state.tags = []
if 'uploaded_pdf_text' not in st.session_state:
    st.session_state.uploaded_pdf_text = None

# File upload section
st.header("Upload Source PDF")
uploaded_file = st.file_uploader("Choose a PDF file", type=['pdf'])

def extract_text_from_pdf(pdf_path):
    try:
        # Convert PDF to images with higher DPI for better OCR
        images = convert_from_path(
            pdf_path,
            dpi=300,  # Higher DPI for better quality
            fmt='png'  # PNG format for better quality
        )
        
        # Configure tesseract parameters for better accuracy
        custom_config = r'--oem 3 --psm 6'
        
        text = ""
        for i, image in enumerate(images):
            # Enhance image for better OCR
            # Convert to RGB if not already
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Extract text with custom configuration
            page_text = pytesseract.image_to_string(
                image, 
                config=custom_config,
                lang='eng'  # Specify English language
            )
            
            text += f"\n--- Page {i+1} ---\n{page_text}\n"
            
            # Show processed image in expander (for debugging)
            with st.expander(f"Show processed image - Page {i+1}"):
                st.image(image, caption=f"Processed Page {i+1}", use_column_width=True)
        
        return text
    
    except Exception as e:
        st.error(f"Error in OCR processing: {str(e)}")
        return None

def clean_text(text):
    """Clean up OCR artifacts and normalize text"""
    # Remove any lines that are just garbage (short lines with random chars)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Keep lines that have meaningful content
        if any([
            'Model #:' in line,
            'Regular Price:' in line,
            'Hearth >' in line,
            len(line) > 20  # Likely a product description
        ]):
            cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)

def parse_pdf_content(text):
    # Clean the text first
    cleaned_text = clean_text(text)
    
    # Debug: Show the cleaned text
    st.write("Cleaned text:")
    st.code(cleaned_text)
    
    tags = []
    
    # Split text into product blocks
    blocks = cleaned_text.split('Hearth >')
    blocks = [b for b in blocks if b.strip()]  # Remove empty blocks
    
    for block in blocks:
        try:
            # Extract model number
            model_match = re.search(r'Model #: ([^\n]+)', block)
            if not model_match:
                continue
            sku = model_match.group(1).strip()
            
            # Extract price
            price_match = re.search(r'Regular Price: \$([0-9.]+)', block)
            if not price_match:
                continue
            price = price_match.group(1).strip()
            
            # Extract product name (everything between model and price)
            lines = block.split('\n')
            model_idx = next(i for i, line in enumerate(lines) if 'Model #:' in line)
            price_idx = next(i for i, line in enumerate(lines) if 'Regular Price:' in line)
            
            # Get product name from lines between model and price
            product_name = ' '.join(line.strip() for line in lines[model_idx+1:price_idx] if line.strip())
            
            # Generate barcode from model number
            barcode = ''.join(filter(str.isalnum, sku))
            
            # Get category
            category = block.split('\n')[0].strip()
            
            # Debug: Show what we found
            st.write(f"Found product: {product_name} (SKU: {sku}, Price: ${price})")
            
            tags.append({
                "productName": product_name,
                "price": price,
                "sku": sku,
                "barcode": barcode,
                "description": f"Category: {category}"
            })
            
        except Exception as e:
            st.write(f"Error processing block: {str(e)}")
            continue
    
    st.write(f"Total tags found: {len(tags)}")
    return tags

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name
    
    try:
        # Extract text from PDF
        extracted_text = extract_text_from_pdf(tmp_file_path)
        st.session_state.uploaded_pdf_text = extracted_text
        
        # Parse the extracted text
        parsed_tags = parse_pdf_content(extracted_text)
        
        if parsed_tags:
            st.success(f"Successfully extracted {len(parsed_tags)} tags from PDF!")
            if st.button("Add extracted tags"):
                st.session_state.tags.extend(parsed_tags)
                st.rerun()
        else:
            st.warning("No tags found in the PDF. Check the format and try again.")
        
        # Show extracted text in expander for debugging
        with st.expander("Show extracted text"):
            st.text(extracted_text)
    
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
