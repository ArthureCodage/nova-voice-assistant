$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$text = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($text)) {
    exit 0
}

$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $speaker.Rate = 1
    $speaker.Volume = 100
    $speaker.Speak($text)
}
finally {
    $speaker.Dispose()
}
