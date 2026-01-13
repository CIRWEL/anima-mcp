#!/bin/bash
# Preview markdown files as HTML or PDF

FILE="$1"
OUTPUT_FORMAT="${2:-html}"

if [ -z "$FILE" ]; then
    echo "Usage: $0 <markdown_file> [html|pdf]"
    echo "Example: $0 docs/NEURO_PSYCH_FRAMING.md html"
    exit 1
fi

if [ ! -f "$FILE" ]; then
    echo "Error: File not found: $FILE"
    exit 1
fi

OUTPUT_FILE="${FILE%.md}.${OUTPUT_FORMAT}"

if [ "$OUTPUT_FORMAT" = "html" ]; then
    pandoc "$FILE" \
        -f markdown \
        -t html \
        --standalone \
        --css=https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown.min.css \
        --metadata title="$(basename "$FILE" .md)" \
        -o "$OUTPUT_FILE"
    
    echo "✅ Created: $OUTPUT_FILE"
    echo "📖 Open in browser: open $OUTPUT_FILE"
    
elif [ "$OUTPUT_FORMAT" = "pdf" ]; then
    pandoc "$FILE" \
        -f markdown \
        -t pdf \
        --pdf-engine=wkhtmltopdf \
        -o "$OUTPUT_FILE" 2>/dev/null || \
    pandoc "$FILE" \
        -f markdown \
        -t pdf \
        -o "$OUTPUT_FILE"
    
    echo "✅ Created: $OUTPUT_FILE"
    echo "📄 Open PDF: open $OUTPUT_FILE"
else
    echo "Error: Unknown format: $OUTPUT_FORMAT (use html or pdf)"
    exit 1
fi

