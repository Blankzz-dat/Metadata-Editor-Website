from flask import Flask, request, redirect, url_for, send_file, jsonify, render_template_string
import os, struct
from io import BytesIO

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

class MetadataFile:
    MAGIC = 0xFAB11BAF
    class StringLiteral:
        def __init__(self, length, offset):
            self.length = length
            self.offset = offset

    def __init__(self, file_path):
        self.filename = file_path
        self.string_literals = []
        self.str_bytes = []
        with open(file_path, "rb") as f:
            self.file_data = bytearray(f.read())
        self.parse()

    def parse(self):
        f = memoryview(self.file_data)
        if struct.unpack_from("<I", f, 0)[0] != self.MAGIC:
            raise Exception("Invalid metadata file")

        self.version = struct.unpack_from("<i", f, 4)[0]
        self.string_literal_offset = struct.unpack_from("<I", f, 8)[0]
        string_literal_table_size = struct.unpack_from("<I", f, 12)[0]
        self.string_literal_count = string_literal_table_size // 8
        self.data_info_position = 16
        self.string_literal_data_offset = struct.unpack_from("<I", f, 16)[0]
        self.string_literal_data_count = struct.unpack_from("<I", f, 20)[0]

        for i in range(self.string_literal_count):
            pos = self.string_literal_offset + i * 8
            length, offset = struct.unpack_from("<II", f, pos)
            self.string_literals.append(self.StringLiteral(length, offset))
            self.str_bytes.append(bytes(f[self.string_literal_data_offset + offset:
                                           self.string_literal_data_offset + offset + length]))

    def get_strings(self):
        return [s.rstrip(b"\x00").decode("utf-8", errors="ignore") for s in self.str_bytes]

    def set_string(self, index, new_value):
        self.str_bytes[index] = new_value.encode("utf-8") + b"\x00"

    def save(self):
        pos = self.string_literal_offset
        offset_count = 0
        for i, lit in enumerate(self.string_literals):
            lit.offset = offset_count
            lit.length = len(self.str_bytes[i])
            struct.pack_into("<II", self.file_data, pos, lit.length, lit.offset)
            pos += 8
            offset_count += lit.length

        padding_needed = (4 - ((self.string_literal_data_offset + offset_count) % 4)) % 4
        if padding_needed:
            end_pos = self.string_literal_data_offset + offset_count
            if end_pos + padding_needed > len(self.file_data):
                self.file_data.extend(b'\x00' * (end_pos + padding_needed - len(self.file_data)))
            self.file_data[end_pos:end_pos+padding_needed] = b'\x00' * padding_needed
            offset_count += padding_needed

        new_pos = self.string_literal_data_offset
        for data in self.str_bytes:
            self.file_data[new_pos:new_pos + len(data)] = data
            new_pos += len(data)

        struct.pack_into("<II", self.file_data, self.data_info_position,
                         self.string_literal_data_offset, offset_count)
        return BytesIO(self.file_data)


@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    if request.method == "POST":
        file = request.files.get("file")
        if file:
            filename = file.filename
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            try:
                # Try to parse once here to catch errors early
                MetadataFile(filepath)
                return redirect(url_for("edit", filename=filename))
            except Exception as e:
                error = f"Failed to parse metadata file: {e}"

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <title>Metadata Editor Upload</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #121212; color: #eee; }
            .container { margin-top: 40px; max-width: 500px; }
            label { font-weight: bold; }
            input[type=file] { background-color: #1e1e1e; color: #eee; }
            button { background-color: #bb86fc; color: black; }
            button:hover { background-color: #9b6cfb; }
            .error { color: #ff6b6b; margin-top: 15px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2 class="mb-4 text-center">Upload Metadata File</h2>
            <form method="POST" enctype="multipart/form-data" class="d-flex flex-column gap-3">
                <input type="file" name="file" required class="form-control form-control-dark">
                <button type="submit" class="btn btn-primary">Upload</button>
            </form>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
        </div>
    </body>
    </html>
    """, error=error)


@app.route("/edit")
def edit():
    filename = request.args.get("filename")
    if not filename:
        return redirect(url_for("index"))
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(filepath):
        return redirect(url_for("index"))

    try:
        meta_obj = MetadataFile(filepath)
    except Exception as e:
        return f"Failed to parse metadata file: {e}", 400

    strings = meta_obj.get_strings()[:100]

    return render_template_string("""
    <!doctype html>
    <html lang="en" data-bs-theme="dark">
    <head>
        <title>Metadata String Editor</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #121212; color: #eee; }
            table tr:hover { background-color: #2c1150 !important; cursor: pointer; }
            #searchBox { max-width: 400px; margin-bottom: 15px; }
            .modal-content {
                background-color: #1e1e1e; color: #eee;
                border: 2px solid #bb86fc;
            }
            .modal-header, .modal-footer {
                border-color: #bb86fc;
            }
            .btn-primary {
                background-color: #bb86fc;
                border-color: #bb86fc;
                color: black;
            }
            .btn-primary:hover {
                background-color: #9b6cfb;
                border-color: #9b6cfb;
                color: black;
            }
        </style>
    </head>
    <body>
    <div class="container mt-3">
        <h2 class="mb-3 text-center">Metadata Strings</h2>
        <input type="text" id="searchBox" class="form-control form-control-dark" placeholder="Search strings...">
        <div class="table-responsive" style="max-height: 70vh; overflow-y: auto;">
        <table class="table table-dark table-hover table-striped" id="stringTable">
            <thead>
                <tr>
                    <th style="width: 60px;">Index</th>
                    <th>String</th>
                </tr>
            </thead>
            <tbody>
            {% for s in strings %}
                <tr data-index="{{ loop.index0 }}">
                    <td>{{ loop.index0 }}</td>
                    <td class="string-cell">{{ s }}</td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
        <div class="text-center mt-3">
            <a href="{{ url_for('download', filename=filename) }}" class="btn btn-outline-light">⬇️ Download Modified File</a>
        </div>
    </div>

    <!-- Modal -->
    <div class="modal fade" id="editModal" tabindex="-1" aria-labelledby="editModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <form id="editForm">
            <div class="modal-header">
              <h5 class="modal-title" id="editModalLabel">Edit String</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" id="editIndex" name="index">
                <input type="hidden" name="filename" value="{{ filename }}">
                <div class="mb-3">
                    <label for="editValue" class="form-label">New String</label>
                    <input type="text" class="form-control form-control-dark" id="editValue" name="new_value" required>
                </div>
            </div>
            <div class="modal-footer">
              <button type="submit" class="btn btn-primary">💾 Save</button>
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const searchBox = document.getElementById('searchBox');
        const table = document.getElementById('stringTable');
        const rows = table.querySelectorAll('tbody tr');
        const editModal = new bootstrap.Modal(document.getElementById('editModal'));
        const editForm = document.getElementById('editForm');
        const editValueInput = document.getElementById('editValue');
        const editIndexInput = document.getElementById('editIndex');

        // Debounce function to limit search frequency
        function debounce(func, wait) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        }

        function filterTable() {
            const filter = searchBox.value.toLowerCase();
            rows.forEach(row => {
                const text = row.querySelector('.string-cell').textContent.toLowerCase();
                row.style.display = text.includes(filter) ? '' : 'none';
            });
        }

        searchBox.addEventListener('input', debounce(filterTable, 200));

        // Click row to open modal
        rows.forEach(row => {
            row.addEventListener('click', () => {
                const idx = row.getAttribute('data-index');
                const text = row.querySelector('.string-cell').textContent;
                editIndexInput.value = idx;
                editValueInput.value = text;
                editModal.show();
                editValueInput.focus();
            });
        });

        // AJAX submit for edit form
        editForm.addEventListener('submit', e => {
            e.preventDefault();
            const data = new FormData(editForm);
            fetch('/update', {
                method: 'POST',
                body: data,
            }).then(resp => {
                if (resp.ok) {
                    const idx = editIndexInput.value;
                    const row = table.querySelector(`tr[data-index="${idx}"]`);
                    if(row) {
                        row.querySelector('.string-cell').textContent = editValueInput.value;
                    }
                    editModal.hide();
                } else {
                    alert('Failed to save.');
                }
            }).catch(() => alert('Network error.'));
        });
    </script>
    </body>
    </html>
    """, strings=strings, filename=filename)


@app.route("/update", methods=["POST"])
def update():
    filename = request.form.get("filename")
    if not filename:
        return jsonify({"error": "Missing filename"}), 400
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    try:
        meta_obj = MetadataFile(filepath)
        index = int(request.form["index"])
        new_value = request.form["new_value"]
        meta_obj.set_string(index, new_value)

        # Save changes back to file
        output = meta_obj.save()
        with open(filepath, "wb") as f:
            f.write(output.read())
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download")
def download():
    filename = request.args.get("filename")
    if not filename:
        return redirect(url_for("index"))
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(filepath):
        return redirect(url_for("index"))

    try:
        meta_obj = MetadataFile(filepath)
        output = meta_obj.save()
        return send_file(output, as_attachment=True, download_name=f"modified-{filename}")
    except Exception as e:
        return f"Failed to prepare file for download: {e}", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
