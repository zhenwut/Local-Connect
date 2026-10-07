param([ValidateSet('start', 'status', 'stop')][string]$Action = 'status')

$ErrorActionPreference = 'Stop'
$request = if ($Action -in @('start', 'stop')) {
    $inputJson = [Console]::In.ReadToEnd()
    if ($inputJson) { $inputJson | ConvertFrom-Json } else { $null }
} else { $null }

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
            $details = netsh interface ipv4 show addresses "name=$alias"
            foreach ($detail in $details) {
                if ($detail -notmatch '(?i)\bIP\b') { continue }
                foreach ($match in [regex]::Matches($detail, '(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')) {
                    $address = $match.Value
                    if ($address -notlike '169.254.*' -and $address -notlike '127.*' -and $address -ne '0.0.0.0') {
                        return $address
                    }
                }
            }
        }
    } catch {
        # The default Windows ICS address is a final fallback.
    }

    $inDirectAdapter = $false
    foreach ($line in (ipconfig)) {
        if ($line -match '^\S.*:\s*$') {
            $inDirectAdapter = $line -match '\*\s*\d+\s*:\s*$'
            continue
        }
        if ($inDirectAdapter -and $line -match '(?i)IPv4.*(?<!\d)192\.168\.137\.1(?!\d)') {
            return '192.168.137.1'
        }
    }
    return $null
}

try {
    $networkInfo = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]
    $tetheringType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
    $profile = $networkInfo::GetInternetConnectionProfile()
    if ($null -eq $profile) { throw 'Windows has no active internet connection profile.' }
    $manager = $tetheringType::CreateFromConnectionProfile($profile)
    $startedByApp = $false
    $previousConfig = $null
    $wasOn = $manager.TetheringOperationalState.ToString() -eq 'On'

    if ($Action -eq 'start') {
        $newPassword = [string]$request.password
        if ($newPassword -cnotmatch '^[A-Za-z0-9]{24}$') { throw 'Missing or invalid hotspot password.' }
        if (-not $wasOn -and $tetheringType::GetTetheringCapabilityFromConnectionProfile($profile).ToString() -ne 'Enabled') {
            throw 'Windows mobile hotspot is unavailable for this network or Wi-Fi adapter.'
        }
        $current = $manager.GetCurrentAccessPointConfiguration()
        $previousConfig = @{ ssid = [string]$current.Ssid; password = [string]$current.Passphrase; was_on = [bool]$wasOn }
        if ($manager.TetheringOperationalState.ToString() -eq 'On') {
            $operation = $manager.StopTetheringAsync()
            $deadline = (Get-Date).AddSeconds(10)
            while ($manager.TetheringOperationalState.ToString() -ne 'Off' -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }
            if ($manager.TetheringOperationalState.ToString() -ne 'Off') { throw 'Windows did not stop the existing hotspot.' }
        }
        $current.Passphrase = $newPassword
        $operation = $manager.ConfigureAccessPointAsync($current)
        $deadline = (Get-Date).AddSeconds(10)
        while (([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne $newPassword -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 200
        }
        if (([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne $newPassword) {
            throw 'Windows did not apply the new hotspot password.'
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
        if ($request.expected_password -and ([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne [string]$request.expected_password) {
            @{ active = $false; skipped = 'Hotspot password changed outside Local Connect.' } | ConvertTo-Json -Compress
            exit 0
        }
        if ($manager.TetheringOperationalState.ToString() -eq 'On') {
            $operation = $manager.StopTetheringAsync()
            $deadline = (Get-Date).AddSeconds(10)
            while ($manager.TetheringOperationalState.ToString() -ne 'Off' -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }
            if ($manager.TetheringOperationalState.ToString() -ne 'Off') { throw 'Windows did not stop the hotspot within 10 seconds.' }
        }
        if ($request.previous_config -and $request.previous_config.password -and $request.previous_config.ssid) {
            $oldConfig = $manager.GetCurrentAccessPointConfiguration()
            $oldConfig.Ssid = [string]$request.previous_config.ssid
            $oldConfig.Passphrase = [string]$request.previous_config.password
            $operation = $manager.ConfigureAccessPointAsync($oldConfig)
            $deadline = (Get-Date).AddSeconds(10)
            while (([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne $oldConfig.Passphrase -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }
            if (([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne $oldConfig.Passphrase) {
                throw 'Windows did not restore the previous hotspot password.'
            }
            if ($request.previous_config.was_on) {
                $operation = $manager.StartTetheringAsync()
                $deadline = (Get-Date).AddSeconds(18)
                while ($manager.TetheringOperationalState.ToString() -ne 'On' -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 200
                }
                if ($manager.TetheringOperationalState.ToString() -ne 'On') {
                    throw 'Windows did not restore the previously enabled hotspot.'
                }
            }
        }
        @{ active = ($manager.TetheringOperationalState.ToString() -eq 'On') } | ConvertTo-Json -Compress
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
        previous_config = $previousConfig
        clients = if ($active) { [int]$manager.ClientCount } else { 0 }
        ssid = if ($config) { $config.Ssid } else { $null }
        password = if ($config) { $config.Passphrase } else { $null }
        ip = $hotspotIp
    } | ConvertTo-Json -Compress
} catch {
    $failure = $_.Exception.Message
    if ($Action -eq 'start' -and $previousConfig -and $manager) {
        try {
            if ($manager.TetheringOperationalState.ToString() -eq 'On') {
                $operation = $manager.StopTetheringAsync()
                $deadline = (Get-Date).AddSeconds(10)
                while ($manager.TetheringOperationalState.ToString() -ne 'Off' -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 200
                }
            }
            if ($manager.TetheringOperationalState.ToString() -eq 'Off') {
                $original = $manager.GetCurrentAccessPointConfiguration()
                $original.Ssid = $previousConfig.ssid
                $original.Passphrase = $previousConfig.password
                $operation = $manager.ConfigureAccessPointAsync($original)
                $deadline = (Get-Date).AddSeconds(10)
                while (([string]$manager.GetCurrentAccessPointConfiguration().Passphrase) -cne $original.Passphrase -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 200
                }
                if ($wasOn) { $operation = $manager.StartTetheringAsync() }
            }
        } catch { }
    }
    @{ active = $false; error = $failure } | ConvertTo-Json -Compress
}
