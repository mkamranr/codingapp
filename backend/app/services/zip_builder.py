import io
import zipfile


def build_zip(files: dict, root_name: str = "", deleted: list = ()) -> bytes:
    """files: path -> content. Paths are placed under root_name/ when given."""
    buf = io.BytesIO()
    prefix = f"{root_name.strip('/')}/" if root_name else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(files):
            zf.writestr(prefix + path, files[path])
        if deleted:
            zf.writestr(
                prefix + "DELETED_FILES.txt",
                "The following files were deleted by the assistant:\n"
                + "\n".join(sorted(deleted)) + "\n",
            )
    return buf.getvalue()
