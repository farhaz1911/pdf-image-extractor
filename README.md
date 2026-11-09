# PDF Image Extractor

A simple desktop app that extracts the images from one or many PDFs and saves them in a folder of your choice.

## Features

- Queue multiple PDFs and process them in one run
- Each PDF gets its own subfolder named after the PDF (duplicates become `name_2`, `name_3`, ...)
- Joins images that a PDF stores as tiles or strips back into one whole picture
- Keeps original quality for normal images, preserves transparency, converts CMYK/JPX to PNG
- Optional filter to skip tiny images (icons, bullets)
- Progress bar and per-file status (`working`, `done`, `failed`)

## Setup

```
pip install -r requirements.txt
```

Requires Python 3.8+ with Tkinter (included on Windows and macOS; on Linux: `sudo apt install python3-tk`).

## Run

```
python pdf_image_extractor.py
```

1. Click **Add PDFs...** and pick one or more files
2. Choose the **Save to** folder
3. Click **Extract Images**

## Notes

- Password-protected PDFs are not supported.
- Vector graphics (charts, drawings) are not embedded images and are not extracted.
- Joined images are rendered from the page, so text drawn on top of a picture will appear in it. Untick the join option to get the raw pieces instead.
