import os
import csv
import platform
import shutil
import subprocess  # needed for clipboard copying via xclip
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk


class NumericEntry(ttk.Entry):
    """
    A custom Entry widget that only allows a valid float (including empty).
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        vcmd = (self.register(self._validate), "%P")
        self.config(validate="key", validatecommand=vcmd)

    def _validate(self, proposed_text):
        if proposed_text == "":
            return True
        try:
            float(proposed_text)
            return True
        except ValueError:
            return False


class LabelingTool(tk.Tk):
    def __init__(self, root_folder, output_csv="labels.csv"):
        super().__init__()

        self.title("Person Track Labeling Tool")
        self.root_folder = root_folder
        self.output_csv = output_csv

        # Collect tracks
        self.tracks = self._get_tracks(root_folder)
        self.n_tracks = len(self.tracks)

        # Load partial labels
        self.labeled_data = self._load_existing_labels(self.output_csv)

        self.current_track_index = 0

        if not os.path.isfile(self.output_csv):
            with open(self.output_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["camera_id", "track_id", "gender", "age"])

        # ----- Styles for "Save & Next" -----
        self.style = ttk.Style(self)
        self.style.configure("Green.TButton", foreground="green")
        self.style.configure("Red.TButton", foreground="red")

        # =====================================================
        #   TOP FRAME: Title, Progress Canvas, and "Go to track"
        # =====================================================
        self.top_frame = ttk.Frame(self)
        self.top_frame.pack(fill=tk.X, padx=5, pady=5)

        # Title label
        self.title_label = ttk.Label(
            self.top_frame, text="", font=("Arial", 30, "bold")
        )
        self.title_label.pack(side=tk.TOP, anchor="w", pady=(0, 5))

        # A frame for progress bar + "Go to track"
        self.nav_frame = ttk.Frame(self.top_frame)
        self.nav_frame.pack(fill=tk.X)

        # PROGRESS BAR (Canvas)
        self.progress_canvas = tk.Canvas(
            self.nav_frame, height=30, bg="white", bd=0, highlightthickness=0
        )
        self.progress_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_canvas.bind("<Button-1>", self._on_progress_click)
        self.progress_canvas.bind("<Configure>", self._on_progress_canvas_configure)
        self.track_rects = []

        # "Go to Track" spinbox + button
        self.goto_frame = ttk.Frame(self.nav_frame)
        self.goto_frame.pack(side=tk.RIGHT, padx=10)

        ttk.Label(self.goto_frame, text="Go to track:").pack(side=tk.LEFT, padx=5)
        self.goto_var = tk.IntVar(value=1)  # 1-based track index
        self.goto_spin = ttk.Spinbox(
            self.goto_frame,
            from_=1,
            to=self.n_tracks if self.n_tracks > 0 else 1,  # avoid an error if no tracks
            textvariable=self.goto_var,
            width=5,
        )
        self.goto_spin.pack(side=tk.LEFT)

        self.goto_button = ttk.Button(
            self.goto_frame, text="Go", command=self._goto_track
        )
        self.goto_button.pack(side=tk.LEFT, padx=5)

        # =============================
        #   MIDDLE: Main Frame + Scrollbar
        # =============================
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.v_scrollbar = ttk.Scrollbar(self.main_frame, orient=tk.VERTICAL)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            self.main_frame,
            bd=0,
            highlightthickness=0,
            yscrollcommand=self.v_scrollbar.set,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scrollbar.config(command=self.canvas.yview)

        self.images_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.images_frame, anchor="nw"
        )
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # =============================
        #   BOTTOM FRAME: gender/age + nav
        # =============================

        self.bottom_frame = ttk.Frame(self)
        self.bottom_frame.pack(fill=tk.X, pady=5)

        # New "Remove Track" Button (placed near "Show Distribution")
        self.remove_button = ttk.Button(
            self.bottom_frame, text="Remove Track", command=self.remove_current_track
        )
        self.remove_button.pack(side=tk.RIGHT, padx=5)

        self.distribution_button = ttk.Button(
            self.bottom_frame, text="Show Distribution", command=self.show_distribution
        )
        self.distribution_button.pack(side=tk.RIGHT, padx=5)

        # Gender
        ttk.Label(self.bottom_frame, text="Gender:").pack(side=tk.LEFT, padx=(10, 2))
        self.gender_var = tk.StringVar(value="")
        self.radio_male = ttk.Radiobutton(
            self.bottom_frame, text="Male", variable=self.gender_var, value="male"
        )
        self.radio_female = ttk.Radiobutton(
            self.bottom_frame, text="Female", variable=self.gender_var, value="female"
        )
        self.radio_male.pack(side=tk.LEFT, padx=2)
        self.radio_female.pack(side=tk.LEFT, padx=2)

        # Age
        ttk.Label(self.bottom_frame, text="  Age:").pack(side=tk.LEFT, padx=(10, 2))
        self.age_var = tk.StringVar()
        self.age_entry = NumericEntry(
            self.bottom_frame, textvariable=self.age_var, width=6
        )
        self.age_entry.pack(side=tk.LEFT, padx=2)

        # Nav Buttons
        self.prev_button = ttk.Button(
            self.bottom_frame, text="Previous", command=self.prev_track
        )
        self.prev_button.pack(side=tk.RIGHT, padx=5)

        self.skip_button = ttk.Button(
            self.bottom_frame, text="Skip", command=self.skip_track
        )
        self.skip_button.pack(side=tk.RIGHT, padx=5)

        self.save_next_button = ttk.Button(
            self.bottom_frame, text="Save & Next", command=self.save_and_next
        )
        self.save_next_button.pack(side=tk.RIGHT, padx=5)

        self.original_images = []
        self.img_labels = []
        self.img_tks = []

        # Enable/Disable Save & Next
        self.age_var.trace_add("write", self._update_save_button_state)
        self.gender_var.trace_add("write", self._update_save_button_state)

        # Show first track
        self.display_current_track()

        # Single-letter shortcuts
        self._setup_shortcuts()

        # Cross-platform maximize
        if platform.system() == "Windows":
            self.state("zoomed")
        else:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry(f"{sw}x{sh}+0+0")

    # ==========================
    #   SHORTCUTS
    # ==========================
    def _setup_shortcuts(self):
        self.bind_all("<KeyPress-m>", self._shortcut_male, add="+")
        self.bind_all("<KeyPress-f>", self._shortcut_female, add="+")
        self.bind_all("<KeyPress-n>", self._shortcut_save_next, add="+")
        self.bind_all("<KeyPress-N>", self._shortcut_save_next, add="+")
        self.bind_all("<KeyPress-p>", self._shortcut_prev, add="+")
        self.bind_all("<KeyPress-i>", self._shortcut_skip, add="+")
        self.bind_all("<KeyPress-a>", self._shortcut_focus_age, add="+")
        self.bind_all("<KeyPress-h>", self._shortcut_help, add="+")
        self.bind_all(
            "<Control-d>", self._shortcut_remove_track, add="+"
        )  # New shortcut

        # Ctrl+A => select all in age field
        self.age_entry.bind("<Control-a>", self._select_all_in_age, add="+")
        self.bind("<Delete>", self._delete_selected_images)

    def _delete_selected_images(self, event):
        indices_to_remove = [
            i
            for i, lbl in enumerate(self.img_labels)
            if getattr(lbl, "selected", False)
        ]
        if not indices_to_remove:
            return

        for index in sorted(indices_to_remove, reverse=True):
            file_path = self.image_paths[index]
            try:
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

            del self.original_images[index]
            del self.image_paths[index]
            lbl = self.img_labels.pop(index)
            lbl.destroy()
            del self.img_tks[index]

        self._flow_images()

    def _shortcut_male(self, event):
        self.gender_var.set("male")
        return "break"

    def _shortcut_female(self, event):
        self.gender_var.set("female")
        return "break"

    def _shortcut_save_next(self, event):
        if str(self.save_next_button["state"]) == "normal":
            self.save_and_next()
        return "break"

    def _shortcut_prev(self, event):
        self.prev_track()
        return "break"

    def _shortcut_skip(self, event):
        self.skip_track()
        return "break"

    def _shortcut_focus_age(self, event):
        self.age_entry.focus_set()
        return "break"

    def _shortcut_help(self, event):
        msg = (
            "Keyboard Shortcuts:\n\n"
            "m = male\n"
            "f = female\n"
            "a = focus age\n"
            "n = save & next\n"
            "p = previous\n"
            "i = skip\n"
            "ctrl+d = remove whole track\n"
            "h = help"
        )
        messagebox.showinfo("Shortcuts", msg)
        return "break"

    def _shortcut_remove_track(self, event):
        self.remove_current_track()
        return "break"

    def remove_current_track(self):
        """Removes the current track from disk and the internal list."""
        if not (0 <= self.current_track_index < self.n_tracks):
            return

        camera_id, track_id, _ = self.tracks[self.current_track_index]
        track_dir = os.path.join(self.root_folder, camera_id, track_id)
        try:
            shutil.rmtree(track_dir)
            print(f"Deleted track directory: {track_dir}")
        except Exception as e:
            messagebox.showerror(
                "Error", f"Failed to delete track directory:\n{track_dir}\n{str(e)}"
            )
            return

        del self.tracks[self.current_track_index]
        self.n_tracks = len(self.tracks)

        if (camera_id, track_id) in self.labeled_data:
            del self.labeled_data[(camera_id, track_id)]
            with open(self.output_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["camera_id", "track_id", "gender", "age"])
                for (c, t), (g, a) in self.labeled_data.items():
                    writer.writerow([c, t, g, a])

        if self.current_track_index >= self.n_tracks:
            self.current_track_index = self.n_tracks - 1

        self.display_current_track()

    def _select_all_in_age(self, event):
        event.widget.select_range(0, "end")
        event.widget.icursor("end")
        return "break"

    # ------------------------------
    # New: Copy Image to Clipboard
    # ------------------------------
    def copy_image_to_clipboard(self, image_path):
        """
        Uses xclip to copy the image at image_path to the clipboard.
        Assumes the image is in PNG format (or a compatible format).
        """
        try:
            subprocess.run(
                [
                    "xclip",
                    "-selection",
                    "clipboard",
                    "-t",
                    "image/png",
                    "-i",
                    image_path,
                ],
                check=True,
            )
            print(f"Copied {image_path} to clipboard.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror(
                "Clipboard Error", f"Failed to copy image to clipboard.\n{e}"
            )

    # ==========================
    #   DATA LOADING
    # ==========================
    def _get_tracks(self, root_folder):
        tracks = []
        for camera_id in sorted(os.listdir(root_folder)):
            cam_path = os.path.join(root_folder, camera_id)
            if not os.path.isdir(cam_path):
                continue
            for track_id in sorted(os.listdir(cam_path)):
                track_path = os.path.join(cam_path, track_id)
                if not os.path.isdir(track_path):
                    continue
                image_paths = [
                    os.path.join(track_path, f)
                    for f in sorted(os.listdir(track_path))
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ]
                if image_paths:
                    tracks.append((camera_id, track_id, image_paths))
        return tracks

    def _load_existing_labels(self, csv_path):
        labeled = {}
        if not os.path.isfile(csv_path):
            return labeled
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return labeled
            for row in reader:
                if len(row) < 4:
                    continue
                cam, tid, gender, age = row[:4]
                labeled[(cam, tid)] = (gender, age)
        return labeled

    # ==========================
    #   DISPLAY / LAYOUT
    # ==========================
    def display_current_track(self):
        self.goto_spin.config(to=self.n_tracks if self.n_tracks > 0 else 1)
        for lbl in self.img_labels:
            lbl.destroy()
        self.img_labels.clear()
        self.img_tks.clear()
        self.original_images.clear()

        if not (0 <= self.current_track_index < self.n_tracks):
            self.title_label.config(
                text="No Tracks Found" if self.n_tracks == 0 else "Out of range"
            )
            return

        camera_id, track_id, img_paths = self.tracks[self.current_track_index]

        self.title_label.config(
            text=f"Camera: {camera_id} | Track: {track_id}   "
            f"[{self.current_track_index + 1}/{self.n_tracks}]"
        )

        if (camera_id, track_id) in self.labeled_data:
            g, a = self.labeled_data[(camera_id, track_id)]
            self.gender_var.set(g)
            self.age_var.set(a)
        else:
            self.gender_var.set("")
            self.age_var.set("")

        self.image_paths = []

        for path in img_paths:
            try:
                pil_img = Image.open(path)
                basename = os.path.basename(path)
                parts = basename.split("_")
                if len(parts) >= 6:
                    try:
                        parts[-1] = os.path.splitext(parts[-1])[0]
                        left = float(parts[-4])
                        top = float(parts[-3])
                        right = float(parts[-2])
                        bottom = float(parts[-1])
                        pil_img = pil_img.crop((left, top, right, bottom))
                    except Exception as e:
                        print(f"Error cropping image {basename}: {e}")
                self.original_images.append(pil_img)
                self.image_paths.append(path)
            except Exception as e:
                print(f"Warning: could not open {path}: {e}")

        # Create placeholders and attach file path to each label
        for i, pil_img in enumerate(self.original_images):
            thumb = pil_img.copy()
            thumb.thumbnail((200, 200), Image.Resampling.LANCZOS)
            imgtk = ImageTk.PhotoImage(thumb)
            lbl = ttk.Label(self.images_frame, image=imgtk)
            lbl.image = imgtk
            lbl.selected = False
            lbl.file_path = self.image_paths[i]
            # Modified: Bind image click to toggle selection and copy image to clipboard
            lbl.bind("<Button-1>", self._on_image_click)
            lbl.pack()
            self.img_labels.append(lbl)
            self.img_tks.append(imgtk)

        self.update_idletasks()
        self._flow_images()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        self._update_save_button_state()
        self._draw_progress_bar()

    def _on_image_click(self, event):
        lbl = event.widget
        lbl.selected = not getattr(lbl, "selected", False)
        if lbl.selected:
            lbl.config(borderwidth=5, relief="solid")
            # Copy the image (using its file path) to the clipboard
            self.copy_image_to_clipboard(lbl.file_path)
        else:
            lbl.config(borderwidth=0, relief="flat")

    def _flow_images(self):
        for lbl in self.img_labels:
            lbl.pack_forget()

        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 1:
            return

        min_img_width = 150
        cols = max(1, canvas_width // min_img_width)
        cell_width = canvas_width // cols

        row = 0
        col = 0
        new_img_tks = []

        for i, pil_img in enumerate(self.original_images):
            w, h = pil_img.size
            ratio = w / h if h != 0 else 1
            scaled_w = cell_width
            scaled_h = int(scaled_w / ratio)

            resized_img = pil_img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
            imgtk = ImageTk.PhotoImage(resized_img)

            lbl = self.img_labels[i]
            lbl.config(image=imgtk)
            lbl.image = imgtk
            new_img_tks.append(imgtk)

            x_pos = col * cell_width
            y_pos = sum(self._row_heights(row))
            lbl.place(x=x_pos, y=y_pos, width=scaled_w, height=scaled_h)

            col += 1
            if col >= cols:
                col = 0
                row += 1

        total_height = 0
        i = 0
        row_heights = []
        while i < len(self.original_images):
            batch = self.original_images[i : i + cols]
            heights = []
            for pil_img in batch:
                w, h = pil_img.size
                ratio = w / h if h != 0 else 1
                scaled_h = int(cell_width / ratio)
                heights.append(scaled_h)
            row_heights.append(max(heights) if heights else 0)
            i += cols
        total_height = sum(row_heights) + 20

        self.images_frame.config(width=canvas_width, height=total_height)
        self.canvas.config(scrollregion=(0, 0, canvas_width, total_height))
        self.img_tks = new_img_tks

    def _row_heights(self, row_index):
        canvas_width = self.canvas.winfo_width()
        min_img_width = 150
        cols = max(1, canvas_width // min_img_width)
        cell_width = canvas_width // cols

        row_heights = []
        i = 0
        while i < len(self.original_images):
            batch = self.original_images[i : i + cols]
            heights = []
            for pil_img in batch:
                w, h = pil_img.size
                ratio = w / h if h != 0 else 1
                scaled_h = int(cell_width / ratio)
                heights.append(scaled_h)
            row_heights.append(max(heights) if heights else 0)
            i += cols

        return row_heights[:row_index]

    def _on_canvas_configure(self, event):
        self._flow_images()

    # ==========================
    #  PROGRESS BAR
    # ==========================

    def _draw_progress_bar(self):
        self.progress_canvas.delete("all")
        self.track_rects.clear()

        if self.n_tracks == 0:
            return

        canvas_width = self.progress_canvas.winfo_width()
        canvas_height = int(self.progress_canvas.winfo_height())
        rect_height = max(canvas_height - 10, 1)
        y1 = 5
        y2 = y1 + rect_height

        rect_width = canvas_width / self.n_tracks

        for i, (cam, tid, _) in enumerate(self.tracks):
            x1 = int(i * rect_width)
            x2 = int((i + 1) * rect_width)
            if (cam, tid) in self.labeled_data:
                gender, age = self.labeled_data[(cam, tid)]
                try:
                    # Convert age to float and check if it's -1 (skipped)
                    if float(age) == -1:
                        fill_color = "yellow"
                    else:
                        fill_color = "green"
                except ValueError:
                    fill_color = "black"
            else:
                fill_color = "black"

            rect_id = self.progress_canvas.create_rectangle(
                x1, y1, x2, y2, fill=fill_color, outline=fill_color, width=0
            )
            if i == self.current_track_index:
                self.progress_canvas.itemconfig(rect_id, outline="red", width=2)

            self.track_rects.append((rect_id, x1, y1, x2, y2, i))

    def _on_progress_canvas_configure(self, event):
        self._draw_progress_bar()

    def _on_progress_click(self, event):
        x, y = event.x, event.y
        for rect_id, x1, y1, x2, y2, track_i in self.track_rects:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.current_track_index = track_i
                self.display_current_track()
                break

    # ==========================
    #  "Go to Track" method
    # ==========================
    def _goto_track(self):
        idx = self.goto_var.get() - 1
        if 0 <= idx < self.n_tracks:
            self.current_track_index = idx
            self.display_current_track()
        else:
            messagebox.showwarning("Invalid", f"Track index {idx + 1} out of range.")

    # ==========================
    #  SAVE BUTTON STATE
    # ==========================
    def _update_save_button_state(self, *args):
        age_str = self.age_var.get().strip()
        try:
            age_val = float(age_str)
        except ValueError:
            age_val = None

        # Allow save & next if the track is marked as skipped (age == -1)
        if age_val is not None and age_val == -1:
            self.save_next_button["state"] = "normal"
            self.save_next_button.configure(style="Green.TButton")
            return

        gender_chosen = self.gender_var.get().strip() != ""
        if age_val is not None and age_val > 0 and age_val < 101 and gender_chosen:
            self.save_next_button["state"] = "normal"
            self.save_next_button.configure(style="Green.TButton")
        else:
            self.save_next_button["state"] = "disabled"
            self.save_next_button.configure(style="Red.TButton")

    # ==========================
    #  NAVIGATION
    # ==========================
    def skip_track(self):
        camera_id, track_id, _ = self.tracks[self.current_track_index]
        self._save_label(camera_id, track_id, "", -1)
        self.current_track_index += 1
        if self.current_track_index < self.n_tracks:
            self.display_current_track()

    def save_and_next(self):
        if not (0 <= self.current_track_index < self.n_tracks):
            return
        camera_id, track_id, _ = self.tracks[self.current_track_index]
        gender = self.gender_var.get()
        age_str = self.age_var.get().strip()
        try:
            age_val = float(age_str)
        except ValueError:
            age_val = 0.0
        self._save_label(camera_id, track_id, gender, age_val)
        self.current_track_index += 1
        if self.current_track_index < self.n_tracks:
            self.display_current_track()

    def prev_track(self):
        self.current_track_index -= 1
        if self.current_track_index >= 0:
            self.display_current_track()
        else:
            messagebox.showinfo("Info", "No previous track.")
            self.current_track_index = 0

    def _save_label(self, cam, tid, gender, age):
        if isinstance(age, (int, float)) and float(age) == -1:
            age_str = "-1"
        else:
            age_str = str(age)
        self.labeled_data[(cam, tid)] = (gender, age_str)
        with open(self.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["camera_id", "track_id", "gender", "age"])
            for (c, t), (g, a) in self.labeled_data.items():
                writer.writerow([c, t, g, a])

    def show_distribution(self):
        import matplotlib.pyplot as plt

        ages = []
        gender_counts = {"male": 0, "female": 0}
        for (cam, tid), (gender, age_str) in self.labeled_data.items():
            try:
                age_val = float(age_str)
                if 0 < age_val < 101:
                    ages.append(age_val)
            except ValueError:
                continue
            if gender in gender_counts:
                gender_counts[gender] += 1

        if not ages:
            messagebox.showinfo("Info", "No labeled data available for plotting.")
            return

        fig, axs = plt.subplots(1, 2, figsize=(10, 4))
        axs[0].hist(ages, bins=range(int(min(ages)), int(max(ages)) + 2))
        axs[0].set_title("Age Distribution")
        axs[0].set_xlabel("Age")
        axs[0].set_ylabel("Count")

        axs[1].bar(gender_counts.keys(), gender_counts.values())
        axs[1].set_title("Gender Distribution")
        axs[1].set_xlabel("Gender")
        axs[1].set_ylabel("Count")

        plt.tight_layout()
        plt.show()


def main():
    root = tk.Tk()
    root.withdraw()

    folder = filedialog.askdirectory(title="Select the data directory")
    if not folder:
        return

    root.destroy()

    output_csv = "labels.csv"
    app = LabelingTool(folder, output_csv)
    app.mainloop()


if __name__ == "__main__":
    main()
