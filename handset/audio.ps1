param([ValidateSet('List','Connect')][string]$Mode = 'List')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
function Emit($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress -Depth 5))
    [Console]::Out.Flush()
}
$connection = $null
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $audio = [Windows.Media.Audio.AudioPlaybackConnection,Windows.Media.Audio,ContentType=WindowsRuntime]
    $deviceInfo = [Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime]
    $collection = [Windows.Devices.Enumeration.DeviceInformationCollection,Windows.Devices.Enumeration,ContentType=WindowsRuntime]
    if ($Mode -eq 'List') {
        $operation = $deviceInfo::FindAllAsync($audio::GetDeviceSelector())
        $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
            Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq ('IAsyncOperation' + [char]96 + '1') } |
            Select-Object -First 1
        if ($null -eq $asTask) { throw 'WinRT device discovery is unavailable.' }
        $task = $asTask.MakeGenericMethod($collection).Invoke($null, @($operation))
        if (-not $task.Wait(15000)) { throw 'Bluetooth device discovery timed out.' }
        $devices = @($task.Result | ForEach-Object { @{id=$_.Id; name=$_.Name} })
        Emit @{devices=$devices}
    } else {
        $request = [Console]::ReadLine() | ConvertFrom-Json
        $connection = $audio::TryCreateFromId([string]$request.id)
        if ($null -eq $connection) { throw 'This device does not support Bluetooth audio reception.' }
        $connection.Start()
        $result = $connection.Open()
        if ($result.Status.ToString() -ne 'Success') {
            throw ('Windows could not open Bluetooth audio: ' + $result.Status.ToString())
        }
        Emit @{phase='connected'; note='Bluetooth audio connected. Select this laptop on iPhone and Speakers in Windows.'}
        # Block when idle; no polling loop or audio decoding in PowerShell/Python.
        # Windows handles A2DP and playback. The parent asks for status on demand.
        while ($null -ne ($command = [Console]::ReadLine())) {
            if ($command -eq 'stop') { break }
            if ($command -eq 'status') {
                if ($connection.State.ToString() -ne 'Opened') {
                    Emit @{phase='disconnected'; note='Bluetooth audio disconnected. Reconnect to listen on the laptop.'}
                    break
                }
                Emit @{phase='connected'; note='Bluetooth audio connected. Select this laptop on iPhone and Speakers in Windows.'}
            }
        }
    }
} catch {
    Emit @{phase='error'; error=$_.Exception.Message}
    exit 1
} finally {
    if ($null -ne $connection) { ([System.IDisposable]$connection).Dispose() }
}
