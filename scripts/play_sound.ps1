param(
    [string]$SoundPath = "sadtrombone.swf.mp3"
)

Add-Type -AssemblyName PresentationCore

$resolved = (Resolve-Path $SoundPath).Path
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([Uri]::new($resolved))
$player.Play()
Start-Sleep -Seconds 5
$player.Close()
