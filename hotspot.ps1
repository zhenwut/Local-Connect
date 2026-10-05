param([ValidateSet('start', 'status', 'stop')][string]$Action = 'status')

$ErrorActionPreference = 'Stop'

function Find-HotspotIp {
    # CIM queries may be denied even when the WinRT hotspot API succeeds.
    try {
        $adapters = Get-NetAdapter -IncludeHidden -ErrorAction Stop | Where-Object {
            $_.Status -eq 'Up' -and $_.InterfaceDescription -like '*Wi-Fi Direct Virtual Adapter*'
        }
        foreach ($adapter in $adapters) {
            $address = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '0.0.0.0' } |
                Select-Object -First 1 -ExpandProperty IPAddress
            if ($address) { return $address }
        }
    } catch {
        # Continue with netsh, which can read interface addresses without CIM access.
    }

    try {
        $interfaces = netsh interface ipv4 show interfaces
        foreach ($line in $interfaces) {
            if ($line -notmatch '^\s*\d+\s+\d+\s+\d+\s+\S+\s+(.+\*\s*\d+)\s*$') { continue }
            $alias = $Matches[1].Trim()
            $details = (netsh interface ipv4 show addresses "name=$alias") -join "`n"
            foreach ($match in [regex]::Matches($details, '(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')) {
                $address = $match.Value
                if ($address -notlike '169.254.*' -and $address -notlike '127.*' -and $address -ne '0.0.0.0') {
                    return $address
                }
            }
        }
    } catch {
        # The default Windows ICS address is a final fallback.
    }

    $ipconfigText = (ipconfig) -join "`n"
    if ($ipconfigText -match '(?<!\d)192\.168\.137\.1(?!\d)') { return '192.168.137.1' }
    return $null
}

try {
    $networkInfo = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]
    $tetheringType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
    $profile = $networkInfo::GetInternetConnectionProfile()
    if ($null -eq $profile) { throw 'Windows has no active internet connection profile.' }
    $manager = $tetheringType::CreateFromConnectionProfile($profile)
    $startedByApp = $false

    if ($Action -eq 'start' -and $manager.TetheringOperationalState.ToString() -ne 'On') {
        if ($tetheringType::GetTetheringCapabilityFromConnectionProfile($profile).ToString() -ne 'Enabled') {
            throw 'Windows mobile hotspot is unavailable for this network or Wi-Fi adapter.'
        }
        $operation = $manager.StartTetheringAsync()
        $deadline = (Get-Date).AddSeconds(18)
        # PowerShell 5.1 may not project IAsyncOperation.Status. Read the actual
        # tethering state instead; the operation must remain alive while it runs.
        while ($manager.TetheringOperationalState.ToString() -ne 'On' -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 200
        }
        if ($manager.TetheringOperationalState.ToString() -ne 'On') { throw 'Windows did not enable the hotspot within 18 seconds.' }
        $startedByApp = $true
    }

    if ($Action -eq 'stop') {
        if ($manager.TetheringOperationalState.ToString() -eq 'On') {
            $operation = $manager.StopTetheringAsync()
            $deadline = (Get-Date).AddSeconds(10)
            while ($manager.TetheringOperationalState.ToString() -ne 'Off' -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }
            if ($manager.TetheringOperationalState.ToString() -ne 'Off') { throw 'Windows did not stop the hotspot within 10 seconds.' }
        }
        @{ active = $false } | ConvertTo-Json -Compress
        exit 0
    }

    $active = $manager.TetheringOperationalState.ToString() -eq 'On'
    $hotspotIp = $null
    if ($active) {
        $deadline = if ($Action -eq 'start') { (Get-Date).AddSeconds(8) } else { Get-Date }
        do {
            $hotspotIp = Find-HotspotIp
            if ($hotspotIp -or (Get-Date) -ge $deadline) { break }
            Start-Sleep -Milliseconds 500
        } while ($true)
    }
    $config = if ($active) { $manager.GetCurrentAccessPointConfiguration() } else { $null }
    @{
        active = $active
        started_by_app = $startedByApp
        clients = if ($active) { [int]$manager.ClientCount } else { 0 }
        ssid = if ($config) { $config.Ssid } else { $null }
        password = if ($config) { $config.Passphrase } else { $null }
        ip = $hotspotIp
    } | ConvertTo-Json -Compress
} catch {
    @{ active = $false; error = $_.Exception.Message; error_line = $_.InvocationInfo.ScriptLineNumber } | ConvertTo-Json -Compress
}
