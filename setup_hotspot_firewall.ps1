#Requires -RunAsAdministrator
param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [string]$HotspotAddress = '192.168.137.1',
    [ValidateRange(1, 32)][int]$PrefixLength = 24,
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
$address = [System.Net.IPAddress]::Parse($HotspotAddress)
if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'HotspotAddress must be an IPv4 address.'
}
if (-not $PythonExe) {
    $probe = 'import sys; print(sys.executable) if sys.version_info >= (3, 10) else sys.exit(1)'
    foreach ($launcher in @('py', 'python')) {
        if (-not (Get-Command $launcher -ErrorAction SilentlyContinue)) { continue }
        $candidateArgs = if ($launcher -eq 'py') { @('-3', '-c', $probe) } else { @('-c', $probe) }
        try {
            $candidate = & $launcher @candidateArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                $PythonExe = [string]$candidate
                break
            }
        } catch { }
    }
    if (-not $PythonExe) { throw 'Could not find Python 3.10 or newer.' }
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Python executable not found.' }

$networkBytes = $address.GetAddressBytes()
for ($index = 0; $index -lt 4; $index++) {
    $bits = [Math]::Min(8, [Math]::Max(0, $PrefixLength - 8 * $index))
    $mask = [int](256 - [Math]::Pow(2, 8 - $bits))
    $networkBytes[$index] = $networkBytes[$index] -band $mask
}
$remoteSubnet = ($networkBytes -join '.') + '/' + $PrefixLength
$ruleName = "LocalConnect-Hotspot-TCP-$Port"
$displayName = "Local Connect PC Hotspot (TCP $Port)"
$settings = @{
    Direction = 'Inbound'
    Action = 'Allow'
    Enabled = 'True'
    Profile = 'Any'
    Protocol = 'TCP'
    LocalPort = $Port
    LocalAddress = $address.ToString()
    RemoteAddress = $remoteSubnet
    Program = $PythonExe
    Description = 'Allow phones on the PC hotspot to reach this Local Connect Python service.'
}
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $ruleName -NewDisplayName $displayName @settings | Out-Null
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName $displayName @settings | Out-Null
}
Write-Output "Allowed TCP ${Port}: $remoteSubnet -> $HotspotAddress ($PythonExe)"
