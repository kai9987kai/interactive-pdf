
# interactive-pdf

A Python-based project for generating and/or processing **interactive PDF workflows** using a clean input/output folder structure.

This repository is organized to keep source PDFs, processing scripts, and generated PDF outputs separated, which makes it easier to test, batch-process, and iterate on PDF automation tasks.

## Features

- **Python-based PDF workflow**
- **Dedicated scripts folder** for processing logic
- **Input staging folder** for source PDFs
- **Output folder** for generated/processed PDFs
- **MIT licensed**
- Includes **Code of Conduct** and **Security Policy**

## Repository Structure

```text
interactive-pdf/
├── scripts/         # Python scripts for PDF processing / generation
├── tmp/
│   └── pdfs/        # Source/input PDFs (temporary working files)
├── output/
│   └── pdf/         # Generated/processed PDF outputs
├── LICENSE
├── CODE_OF_CONDUCT.md
└── SECURITY.md
````

## What this project is for

This repo is a good foundation for tasks like:

* Creating interactive PDF forms
* Filling existing PDF forms programmatically
* Batch processing PDF files
* Converting templates into reusable form documents
* Building small PDF automation pipelines

> Depending on your script implementation, “interactive PDF” may include form fields (text boxes, checkboxes, dropdowns), links, buttons, annotations, or scripted PDF actions.

## Requirements

* **Python 3.9+** (recommended)
* PDF libraries (depends on your scripts), commonly:

  * `pypdf` / `PyPDF2`
  * `pdfrw`
  * `reportlab`
  * `pymupdf` (`fitz`)
  * `fpdf2`

If your repo has a `requirements.txt`, install with:

```bash
pip install -r requirements.txt
```

Otherwise install the libraries used by your scripts manually, e.g.:

```bash
pip install pypdf reportlab
```

## Quick Start

### 1) Clone the repository

```bash
git clone https://github.com/kai9987kai/interactive-pdf.git
cd interactive-pdf
```

### 2) Add your source PDFs

Put the PDFs you want to process in:

```text
tmp/pdfs/
```

### 3) Run the processing script(s)

Run your Python scripts from the `scripts/` folder.

Examples (replace with your actual script names):

```bash
python scripts/main.py
```

or

```bash
python scripts/process_pdf.py
```

or batch-run all scripts one-by-one (PowerShell):

```powershell
Get-ChildItem .\scripts\*.py | ForEach-Object { python $_.FullName }
```

### 4) Check the output

Processed/generated PDFs should appear in:

```text
output/pdf/
```

## Typical Workflow

1. **Drop PDF templates or source documents** into `tmp/pdfs/`
2. **Run a script** from `scripts/`
3. **Inspect generated results** in `output/pdf/`
4. **Adjust script logic** (field placement, naming, values, annotations, etc.)
5. Re-run until the output matches your desired interactive behavior

## Example Use Cases

* **Form generation**

  * Add text fields, checkboxes, radio buttons, dropdowns
* **Form filling**

  * Populate existing PDF form fields from Python data
* **Document automation**

  * Generate repeatable forms/invoices/worksheets
* **Template pipelines**

  * Read PDFs from `tmp/pdfs/`, process them, save to `output/pdf/`

## Development Tips

### Keep inputs and outputs separate

Using `tmp/pdfs/` for incoming files and `output/pdf/` for generated files avoids overwriting originals and makes debugging much easier.

### Use deterministic filenames

For batch jobs, save outputs with predictable names, e.g.:

* `form_filled_001.pdf`
* `invoice_2026-02-23.pdf`
* `template_interactive_v2.pdf`

### Validate in multiple PDF viewers

Interactive features can behave differently depending on the PDF viewer:

* Adobe Acrobat Reader
* Browser PDF viewers (Chrome/Edge)
* macOS Preview (some features may be limited)

## Troubleshooting

### Output PDF not appearing

* Confirm your script writes to `output/pdf/`
* Ensure the directory exists (create it in code if needed)
* Check for path separator issues on Windows vs macOS/Linux

### Form fields don’t show correctly

* Some libraries require appearance streams or field flags to be set
* Test the file in Adobe Acrobat Reader for better compatibility
* Ensure field names are unique if generating many fields

### Script can’t find input PDF

* Verify the file is inside `tmp/pdfs/`
* Use absolute paths during debugging
* Print resolved paths in your script to confirm

## Suggested Improvements (optional)

If you want to grow this repo, consider adding:

* `requirements.txt`
* `README` examples with screenshots/GIFs
* CLI support (`argparse`) for:

  * `--input`
  * `--output`
  * `--batch`
* Logging (`logging` module)
* Automated tests for PDF generation output
* Sample PDFs in `tmp/pdfs/` (or a `samples/` folder)

## Contributing

Contributions are welcome.

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Test with sample PDFs
5. Open a pull request

Please read the included **Code of Conduct** and **Security Policy** before contributing.

## License

This project is licensed under the **MIT License**. See [`LICENSE`](./LICENSE).

## Author

**Kai Piper**
GitHub: [@kai9987kai](https://github.com/kai9987kai)

"GitHub - kai9987kai/interactive-pdf"
