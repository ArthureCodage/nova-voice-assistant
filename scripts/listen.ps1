param(
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
if ($installed.Count -eq 0) {
    throw "Aucun moteur de reconnaissance vocale Windows n'est installé."
}

$culture = [System.Globalization.CultureInfo]::CurrentUICulture
$match = $installed | Where-Object { $_.Culture.Name -eq $culture.Name } | Select-Object -First 1
if ($null -eq $match) {
    $match = $installed | Select-Object -First 1
}

$recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($match)
try {
    $recognizer.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $recognizer.SetInputToDefaultAudioDevice()
    $result = $recognizer.Recognize([TimeSpan]::FromSeconds($TimeoutSeconds))
    if ($null -ne $result) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        [Console]::Write($result.Text)
    }
}
finally {
    $recognizer.Dispose()
}
