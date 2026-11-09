"""
PDF Image Extractor
-------------------
Pick a PDF, pick a folder, and save every embedded image from the PDF.

Setup (one time):
    pip install pymupdf

Run:
    python pdf_image_extractor.py
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def group_rects(rects, tol=1.5):
    """Group rectangles that touch or overlap (pieces of one split image)."""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [fitz.Rect(r) for r in rects]
    for i in range(n):
        a = fitz.Rect(boxes[i].x0 - tol, boxes[i].y0 - tol, boxes[i].x1 + tol, boxes[i].y1 + tol)
        for j in range(i + 1, n):
            if a.intersects(boxes[j]):
                parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def save_single(doc, xref, smask, base_path):
    """Save one embedded image at its original quality. Returns the file path."""
    info = doc.extract_image(xref)
    if not smask and info["ext"] in ("jpeg", "jpg", "png"):
        path = f"{base_path}.{info['ext']}"
        with open(path, "wb") as f:
            f.write(info["image"])
        return path
    pix = fitz.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:  # CMYK -> RGB
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if smask:  # keep transparency
        pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
    path = base_path + ".png"
    pix.save(path)
    return path


def extract_images(pdf_path, out_dir, skip_tiny, merge_split, log, progress):
    """Extract all images. Returns the number of images saved."""
    doc = fitz.open(pdf_path)
    if doc.needs_pass:
        raise RuntimeError("This PDF is password-protected.")

    base = os.path.splitext(os.path.basename(pdf_path))[0]
    seen, saved = set(), 0
    total = len(doc)

    for page_index in range(total):
        page = doc[page_index]
        smasks = {img[0]: img[1] for img in page.get_images(full=True)}
        infos = page.get_image_info(xrefs=True)
        if not infos:
            progress((page_index + 1) / total * 100)
            continue

        if merge_split:
            groups = group_rects([i["bbox"] for i in infos])
        else:
            groups = [[i] for i in range(len(infos))]

        for idxs in groups:
            try:
                name = f"{base}_p{page_index + 1}_img{saved + 1}"
                base_path = os.path.join(out_dir, name)
                first = infos[idxs[0]]

                if len(idxs) == 1 and first["xref"] > 0:
                    # A normal, whole image: save the original file
                    xref = first["xref"]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    if skip_tiny and (first["width"] < 50 or first["height"] < 50):
                        continue
                    path = save_single(doc, xref, smasks.get(xref, 0), base_path)
                else:
                    # Several pieces of one picture: render the area as one image
                    rect = fitz.Rect(infos[idxs[0]]["bbox"])
                    scale = 1.0
                    for i in idxs:
                        r = fitz.Rect(infos[i]["bbox"])
                        rect |= r
                        if r.width > 0 and r.height > 0:
                            scale = max(scale, infos[i]["width"] / r.width,
                                        infos[i]["height"] / r.height)
                    rect &= page.rect
                    scale = min(scale, 8.0)
                    # keep memory sane: cap at ~120 megapixels
                    while rect.width * rect.height * scale * scale > 120e6 and scale > 1:
                        scale *= 0.9
                    if skip_tiny and (rect.width * scale < 50 or rect.height * scale < 50):
                        continue
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                          clip=rect, alpha=False)
                    path = base_path + ".png"
                    pix.save(path)
                    log(f"Merged {len(idxs)} pieces into one image")

                saved += 1
                log(f"Saved {os.path.basename(path)}")
            except Exception as e:
                log(f"Skipped an image on page {page_index + 1}: {e}")

        progress((page_index + 1) / total * 100)

    doc.close()
    return saved


def unique_folder(out_root, pdf_path, used):
    """Folder named after the PDF; adds _2, _3... if two PDFs share a name."""
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{name}_{n}"
        n += 1
    used.add(candidate.lower())
    return os.path.join(out_root, candidate)


def run_queue(pdfs, out_root, skip_tiny, merge_split, log, progress, file_status=None):
    """Process every PDF in order, each into its own subfolder. Returns (files_ok, images)."""
    used, ok, images = set(), 0, 0
    total = len(pdfs)
    for n, pdf in enumerate(pdfs):
        name = os.path.basename(pdf)
        if file_status:
            file_status(n, "working")
        log(f"\n[{n + 1}/{total}] {name}")
        try:
            folder = unique_folder(out_root, pdf, used)
            os.makedirs(folder, exist_ok=True)
            count = extract_images(
                pdf, folder, skip_tiny, merge_split, log,
                lambda p, n=n: progress((n + p / 100) / total * 100),
            )
            log(f"{count} image(s) saved to {folder}" if count
                else "No embedded images found in this PDF.")
            images += count
            ok += 1
            if file_status:
                file_status(n, "done")
        except Exception as e:
            log(f"Error: {e}")
            if file_status:
                file_status(n, "failed")
        progress((n + 1) / total * 100)
    return ok, images


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Image Extractor")
        self.geometry("680x620")
        self.minsize(560, 520)

        self.queue = []  # list of PDF paths
        self.out_var = tk.StringVar()
        self.skip_var = tk.BooleanVar(value=False)
        self.merge_var = tk.BooleanVar(value=True)

        pad = {"padx": 12, "pady": 6}
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(8, weight=2)

        ttk.Label(frame, text="PDF queue (processed top to bottom):").grid(
            row=0, column=0, sticky="w", **pad)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=12)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, selectmode="extended", height=6, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=sb.set)

        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, sticky="w", padx=12, pady=6)
        self.add_btn = ttk.Button(btns, text="Add PDFs…", command=self.add_files)
        self.rem_btn = ttk.Button(btns, text="Remove selected", command=self.remove_selected)
        self.clr_btn = ttk.Button(btns, text="Clear all", command=self.clear_queue)
        for b in (self.add_btn, self.rem_btn, self.clr_btn):
            b.pack(side="left", padx=(0, 8))

        out_row = ttk.Frame(frame)
        out_row.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        out_row.columnconfigure(1, weight=1)
        ttk.Label(out_row, text="Save to:").grid(row=0, column=0, sticky="w")
        ttk.Entry(out_row, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=8)
        self.out_btn = ttk.Button(out_row, text="Browse…", command=self.pick_folder)
        self.out_btn.grid(row=0, column=2)
        ttk.Label(
            frame, foreground="gray",
            text="Each PDF gets its own subfolder here, named after the PDF.",
        ).grid(row=4, column=0, sticky="w", padx=12)

        self.skip_chk = ttk.Checkbutton(
            frame, text="Skip tiny images (icons, bullets, under 50 px)", variable=self.skip_var)
        self.skip_chk.grid(row=5, column=0, sticky="w", padx=12, pady=2)
        self.merge_chk = ttk.Checkbutton(
            frame, text="Join split images back into whole pictures (recommended)",
            variable=self.merge_var)
        self.merge_chk.grid(row=6, column=0, sticky="w", padx=12, pady=2)

        self.btn = ttk.Button(frame, text="Extract Images", command=self.start)
        self.btn.grid(row=7, column=0, pady=8)

        self.bar = ttk.Progressbar(frame, maximum=100)
        self.bar.grid(row=9, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.log_box = tk.Text(frame, height=8, state="disabled", wrap="word")
        self.log_box.grid(row=8, column=0, sticky="nsew", padx=12, pady=(0, 6))

        self.controls = [self.add_btn, self.rem_btn, self.clr_btn, self.out_btn,
                         self.skip_chk, self.merge_chk, self.btn]

        if fitz is None:
            self.btn.state(["disabled"])
            self.log("PyMuPDF is not installed. Run:  pip install pymupdf  then restart.")

    # ---- queue handling ----
    def refresh_list(self, statuses=None):
        self.listbox.delete(0, "end")
        for i, p in enumerate(self.queue):
            tag = f"  [{statuses[i]}]" if statuses and i in statuses else ""
            self.listbox.insert("end", os.path.basename(p) + tag)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PDFs to add", filetypes=[("PDF files", "*.pdf")])
        added = 0
        for p in paths:
            p = os.path.normpath(p)
            if p not in self.queue:
                self.queue.append(p)
                added += 1
        if added and not self.out_var.get():
            self.out_var.set(os.path.join(os.path.dirname(self.queue[0]), "extracted_images"))
        self.refresh_list()

    def remove_selected(self):
        for i in sorted(self.listbox.curselection(), reverse=True):
            del self.queue[i]
        self.refresh_list()

    def clear_queue(self):
        self.queue.clear()
        self.refresh_list()

    def pick_folder(self):
        path = filedialog.askdirectory(title="Choose a folder for the images")
        if path:
            self.out_var.set(path)

    # ---- running ----
    def log(self, msg):
        def write():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, write)

    def set_progress(self, value):
        self.after(0, lambda: self.bar.config(value=value))

    def set_controls(self, enabled):
        for c in self.controls:
            c.state(["!disabled" if enabled else "disabled"])

    def start(self):
        out = self.out_var.get().strip()
        if not self.queue:
            messagebox.showwarning("Empty queue", "Add at least one PDF first.")
            return
        if not out:
            messagebox.showwarning("No folder", "Please choose a folder to save the images in.")
            return

        os.makedirs(out, exist_ok=True)
        self.set_controls(False)
        self.bar.config(value=0)
        self.statuses = {}
        threading.Thread(target=self.worker, args=(list(self.queue), out), daemon=True).start()

    def file_status(self, index, state):
        def update():
            self.statuses[index] = state
            self.refresh_list(self.statuses)
        self.after(0, update)

    def worker(self, pdfs, out):
        try:
            ok, images = run_queue(
                pdfs, out, self.skip_var.get(), self.merge_var.get(),
                self.log, self.set_progress, self.file_status)
            self.log(f"\nAll done. {ok}/{len(pdfs)} PDF(s) processed, "
                     f"{images} image(s) saved in:\n{out}")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self.after(0, lambda: self.set_controls(True))


if __name__ == "__main__":
    App().mainloop()
