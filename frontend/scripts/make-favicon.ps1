# Generates a multi-size favicon.ico + apple-touch-icon.png from a source PNG.
# ICO container is assembled by hand because .NET has no built-in .ico encoder.
# PNG-compressed entries are valid inside .ico and are handled by every modern
# browser.
param(
    [string]$Source = 'C:\Users\polav\Desktop\project\frontend\public\logo.png',
    [string]$OutDir = 'C:\Users\polav\Desktop\project\frontend\public'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$src = [System.Drawing.Image]::FromFile($Source)

function New-ScaledBitmap([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap(
        $size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.PixelOffsetMode  = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.SmoothingMode    = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.DrawImage($script:src, 0, 0, $size, $size)
    $g.Dispose()
    return $bmp
}

$sizes = @(16, 32, 48)
$entries = @()

foreach ($s in $sizes) {
    $bmp = New-ScaledBitmap $s
    $ms  = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $entries += ,@{ size = $s; bytes = $ms.ToArray() }
    $bmp.Dispose(); $ms.Dispose()
}

# --- assemble ICO -------------------------------------------------------
$ico = New-Object System.IO.MemoryStream
$bw  = New-Object System.IO.BinaryWriter($ico)
$bw.Write([UInt16]0)          # reserved
$bw.Write([UInt16]1)          # type 1 = icon
$bw.Write([UInt16]$entries.Count)

$offset = 6 + (16 * $entries.Count)
foreach ($e in $entries) {
    $dim = if ($e.size -ge 256) { 0 } else { $e.size }
    $bw.Write([byte]$dim)          # width
    $bw.Write([byte]$dim)          # height
    $bw.Write([byte]0)             # palette size
    $bw.Write([byte]0)             # reserved
    $bw.Write([UInt16]1)           # colour planes
    $bw.Write([UInt16]32)          # bits per pixel
    $bw.Write([UInt32]$e.bytes.Length)
    $bw.Write([UInt32]$offset)
    $offset += $e.bytes.Length
}
foreach ($e in $entries) { $bw.Write($e.bytes) }
$bw.Flush()

$icoPath = Join-Path $OutDir 'favicon.ico'
[System.IO.File]::WriteAllBytes($icoPath, $ico.ToArray())
$bw.Dispose(); $ico.Dispose()

# --- apple touch icon (iOS home screen) ---------------------------------
$apple = New-ScaledBitmap 180
$apple.Save((Join-Path $OutDir 'apple-touch-icon.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$apple.Dispose()

$src.Dispose()

Write-Output "wrote favicon.ico          ($((Get-Item $icoPath).Length) bytes, sizes: $($sizes -join ', '))"
Write-Output "wrote apple-touch-icon.png ($((Get-Item (Join-Path $OutDir 'apple-touch-icon.png')).Length) bytes, 180x180)"