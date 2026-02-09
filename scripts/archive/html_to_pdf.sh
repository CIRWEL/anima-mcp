#!/bin/bash
# Convert HTML to PDF using macOS's built-in tools

HTML_FILE="$1"
PDF_FILE="${HTML_FILE%.html}.pdf"

if [ -z "$HTML_FILE" ] || [ ! -f "$HTML_FILE" ]; then
    echo "Usage: $0 <html_file>"
    exit 1
fi

# Use macOS's built-in textutil or we can use Python with weasyprint
if command -v python3 &> /dev/null; then
    python3 << EOF
import sys
try:
    from weasyprint import HTML
    HTML(filename='$HTML_FILE').write_pdf('$PDF_FILE')
    print(f"✅ Created: $PDF_FILE")
except ImportError:
    print("Installing weasyprint...")
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'weasyprint', '--quiet'])
    from weasyprint import HTML
    HTML(filename='$HTML_FILE').write_pdf('$PDF_FILE')
    print(f"✅ Created: $PDF_FILE")
EOF
else
    echo "Python3 not found. Please install weasyprint manually:"
    echo "  pip install weasyprint"
    echo "  python3 -m weasyprint $HTML_FILE $PDF_FILE"
fi

