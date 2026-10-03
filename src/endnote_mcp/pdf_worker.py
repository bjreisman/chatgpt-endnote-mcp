"""Private extraction subprocess: one UTF-8 JSON result, no partial success."""
import json
import sys


def main():
    # Import and native diagnostics are captured by the parent, never MCP stdout.
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        with pymupdf.open(sys.argv[1]) as document:
            if document.needs_pass:
                raise ValueError('PDF requires a password')
            pages = []
            for index, page in enumerate(document, 1):
                text = page.get_text('text').strip()
                if text:
                    pages.append((index, text))
        result = {'pages': pages}
    except Exception as exc:
        result = {'error': str(exc)[:2000]}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
