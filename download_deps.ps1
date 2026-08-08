# Run this on a machine WITH internet access
# It downloads epub.js and pdf.js into the static/ folder
# Then copy the static/ folder back to the book_organiser project

$staticDir = Join-Path $PSScriptRoot "static"
New-Item -ItemType Directory -Path $staticDir -Force | Out-Null

$files = @(
    @{url="https://cdnjs.cloudflare.com/ajax/libs/epub.js/0.3.88/epub.min.js"; file="epub.min.js"},
    @{url="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"; file="pdf.min.js"}
)

foreach ($f in $files) {
    $dest = Join-Path $staticDir $f.file
    if (-not (Test-Path $dest)) {
        Write-Host "Downloading $($f.url)..."
        Invoke-WebRequest -Uri $f.url -OutFile $dest
        Write-Host "  -> saved to $dest"
    } else {
        Write-Host "$($f.file) already exists, skipping"
    }
}
Write-Host "Done. Copy the 'static' folder to your book_organiser project."
