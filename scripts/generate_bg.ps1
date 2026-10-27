Add-Type -AssemblyName System.Drawing

$SrcPath = "static/img/cyberpunk_splash.jpg"
$DstPath = "static/img/cyberpunk_bg.png"

if (-not (Test-Path $SrcPath)) {
    Write-Error "Source image not found: $SrcPath"
    exit 1
}

$src = [System.Drawing.Bitmap]::new($SrcPath)
$w = 1920
$h = 1080
$dest = [System.Drawing.Bitmap]::new($w, $h)
$g = [System.Drawing.Graphics]::FromImage($dest)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

# Deep background fill #0b1120
$bgColor = [System.Drawing.Color]::FromArgb(255, 11, 17, 32)
$brush = [System.Drawing.SolidBrush]::new($bgColor)
$g.FillRectangle($brush, 0, 0, $w, $h)

# ColorMatrix: dim RGB to 0.35 (subtle, tenue) so neon glows are visible but gentle
$matrix = [System.Drawing.Imaging.ColorMatrix]::new()
$matrix.Matrix00 = 0.32
$matrix.Matrix11 = 0.32
$matrix.Matrix22 = 0.32
$matrix.Matrix33 = 1.00

$ia = [System.Drawing.Imaging.ImageAttributes]::new()
$ia.SetColorMatrix($matrix)

$rect = [System.Drawing.Rectangle]::new(0, 0, $w, $h)
$g.DrawImage($src, $rect, 0, 0, $src.Width, $src.Height, [System.Drawing.GraphicsUnit]::Pixel, $ia)

# Optional central vignette overlay to soften behind the card
$overlayBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(120, 11, 17, 32))
$centerRect = [System.Drawing.Rectangle]::new(($w - 750) / 2, ($h - 600) / 2, 750, 600)
$g.FillRectangle($overlayBrush, $centerRect)

$g.Dispose()
$dest.Save($DstPath, [System.Drawing.Imaging.ImageFormat]::Png)
$dest.Dispose()
$src.Dispose()

Write-Host "Created $DstPath successfully ($w x $h)"
