# Docx.py
import os
import mammoth


class Docx:
    def process_docx(self, file_path):
        try:
            with open(file_path, "rb") as docx_file:
                result = mammoth.convert_to_markdown(docx_file)
                md_content = f"# Document: {os.path.basename(file_path)}\n\n"
                md_content += result.value
            
                if result.messages:
                    md_content += "\n\n## Conversion Notes\n\n"
                    for message in result.messages:
                        md_content += f"- {message.message}\n"
                
                return md_content
        except Exception as e:
            return f"# Error Processing {os.path.basename(file_path)}\n\nAn error occurred: {str(e)}"
