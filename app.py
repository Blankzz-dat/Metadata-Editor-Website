from flask import Flask, request, redirect, url_for, send_file, jsonify, render_template_string
import os, struct
from io import BytesIO

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------- MetadataFile Class -------------------
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


# ------------------- Routes -------------------
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
                MetadataFile(filepath)
                return redirect(url_for("edit", filename=filename))
            except Exception as e:
                error = f"Failed to parse metadata file: {e}"

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <title>Upload Metadata</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>body{background:#121212;color:#eee}.container{margin-top:50px;max-width:400px}</style>
    </head>
    <body>
        <div class="container">
            <h3>Upload Metadata File</h3>
            <form method="POST" enctype="multipart/form-data" class="d-flex flex-column gap-3">
                <input type="file" name="file" required class="form-control">
                <button class="btn btn-primary">Upload</button>
            </form>
            {% if error %}<div class="text-danger mt-3">{{ error }}</div>{% endif %}
        </div>
    </body>
    </html>
    """, error=error)


@app.route("/edit")
def edit():
    filename = request.args.get("filename")
    if not filename:
        return redirect(url_for("index"))
    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <title>Metadata Editor</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body{background:#121212;color:#eee}
            table tr:hover{background:#2c1150;cursor:pointer}
            #pagination{margin-top:10px}
        </style>
    </head>
    <body>
        <div class="container mt-3">
            <h2>Metadata Strings (Page <span id="pageNum">1</span>)</h2>
            <table class="table table-dark table-hover table-striped" id="stringTable">
                <thead><tr><th>Index</th><th>String</th></tr></thead><tbody></tbody>
            </table>
            <div id="pagination" class="d-flex justify-content-between">
                <button id="prevBtn" class="btn btn-secondary" disabled>⬅ Prev</button>
                <button id="nextBtn" class="btn btn-primary">Next ➡</button>
            </div>
            <div class="text-center mt-3">
                <a href="{{ url_for('download', filename=filename) }}" class="btn btn-outline-light">⬇ Download Modified</a>
            </div>
        </div>

        <!-- Edit Modal -->
        <div class="modal fade" id="editModal" tabindex="-1">
          <div class="modal-dialog">
            <div class="modal-content bg-dark text-light">
              <div class="modal-header"><h5 class="modal-title">Edit String</h5></div>
              <div class="modal-body">
                <input type="hidden" id="editIndex">
                <input type="text" id="editValue" class="form-control">
              </div>
              <div class="modal-footer">
                <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <button class="btn btn-primary" id="saveEdit">Save</button>
              </div>
            </div>
          </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script>
            let currentPage=1, limit=10;
            const tableBody=document.querySelector("#stringTable tbody");
            const prevBtn=document.getElementById("prevBtn");
            const nextBtn=document.getElementById("nextBtn");
            const pageNum=document.getElementById("pageNum");
            const editModal=new bootstrap.Modal(document.getElementById("editModal"));
            const editValue=document.getElementById("editValue");
            const editIndex=document.getElementById("editIndex");

            function loadPage(page){
                fetch(`/get_strings_page?filename={{ filename }}&page=${page}&limit=${limit}`)
                .then(r=>r.json()).then(data=>{
                    tableBody.innerHTML="";
                    data.strings.forEach((s,i)=>{
                        tableBody.insertAdjacentHTML('beforeend',
                            `<tr data-index="${data.start_index+i}"><td>${data.start_index+i}</td><td>${s}</td></tr>`);
                    });
                    document.querySelectorAll("tr[data-index]").forEach(row=>{
                        row.addEventListener("click",()=>{
                            editIndex.value=row.dataset.index;
                            editValue.value=row.children[1].textContent;
                            editModal.show();
                        });
                    });
                    currentPage=page;
                    pageNum.textContent=page;
                    prevBtn.disabled=(page===1);
                    nextBtn.disabled=!data.has_more;
                });
            }

            prevBtn.addEventListener("click",()=>loadPage(currentPage-1));
            nextBtn.addEventListener("click",()=>loadPage(currentPage+1));
            document.getElementById("saveEdit").addEventListener("click",()=>{
                fetch("/update",{method:"POST",body:new URLSearchParams({
                    index:editIndex.value,new_value:editValue.value,filename:"{{ filename }}"
                })}).then(r=>r.json()).then(resp=>{
                    if(resp.success){
                        const row=document.querySelector(`tr[data-index="${editIndex.value}"] td:nth-child(2)`);
                        if(row) row.textContent=editValue.value;
                        editModal.hide();
                    } else alert("Save failed: "+resp.error);
                });
            });

            loadPage(1);
        </script>
    </body>
    </html>
    """, filename=filename)


@app.route("/get_strings_page")
def get_strings_page():
    filename = request.args.get("filename")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 10))

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    meta_obj = MetadataFile(filepath)
    all_strings = meta_obj.get_strings()

    start = (page - 1) * limit
    end = min(start + limit, len(all_strings))
    batch = all_strings[start:end]

    return jsonify({
        "strings": batch,
        "start_index": start,
        "has_more": end < len(all_strings)
    })


@app.route("/update", methods=["POST"])
def update():
    filename = request.form.get("filename")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    try:
        meta_obj = MetadataFile(filepath)
        index = int(request.form["index"])
        new_value = request.form["new_value"]
        meta_obj.set_string(index, new_value)

        with open(filepath, "wb") as f:
            f.write(meta_obj.save().read())
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download")
def download():
    filename = request.args.get("filename")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not filename or not os.path.isfile(filepath):
        return redirect(url_for("index"))

    meta_obj = MetadataFile(filepath)
    return send_file(meta_obj.save(), as_attachment=True, download_name=f"modified-{filename}")


# ------------------- Run -------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
