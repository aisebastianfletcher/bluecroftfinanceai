import os

def save_uploaded_file(uploaded_file, dest_dir="output/generated_pdfs"):
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, uploaded_file.name)
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest
