param(
    [Parameter(Mandatory=$true)][string]$Organization,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
# Read only the marked billing window; never send keystrokes or change its focus.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [Windows.Automation.AutomationElement]::RootElement
$scope = [Windows.Automation.TreeScope]
function Controls($parent, $type) {
    $condition = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::ControlTypeProperty, $type)
    return $parent.FindAll($scope::Descendants, $condition)
}
function IsBillingWindow($window) {
    if ($window.Current.Name -notmatch 'Billing.*Claude Platform.*Brave') { return $false }
    foreach ($edit in (Controls $window ([Windows.Automation.ControlType]::Edit))) {
        $pattern = $null
        if ($edit.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern) -and
            $pattern.Current.Value -ceq 'https://platform.claude.com/settings/billing#pooledge-credit') { return $true }
    }
    return $false
}
$windows = @($root.FindAll($scope::Children, [Windows.Automation.Condition]::TrueCondition) |
    Where-Object { IsBillingWindow $_ })
if ($windows.Count -ne 1) { throw 'Se requiere una ventana de facturacion marcada.' }
$window = $windows[0]
$document = @(Controls $window ([Windows.Automation.ControlType]::Document))[0]
$reload = @(Controls $window ([Windows.Automation.ControlType]::Button) |
    Where-Object { $_.Current.Name -in 'Volver a cargar','Reload','Reload this page','Actualizar' })
if ($reload.Count -ne 1) { throw 'No se encontro el control de recarga.' }
$oldBalance = @(Controls $document ([Windows.Automation.ControlType]::Text) | Where-Object { $_.Current.Name -eq 'Credit balance' })[0]
$reload[0].GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
$reloaded = $false
for ($i = 0; $i -lt 100; $i++) {
    Start-Sleep -Milliseconds 150
    try {
        $current = @(Controls $window ([Windows.Automation.ControlType]::Document))[0]
        if (!$current -or ![Windows.Automation.Automation]::Compare($document, $current)) { $reloaded = $true }
        if (!$reloaded) {
            $waiting = @(Controls $window ([Windows.Automation.ControlType]::Button) | Where-Object { $_.Current.Name -match '^(Detener|Stop loading|Stop$)' })
            $balance = @(Controls $current ([Windows.Automation.ControlType]::Text) | Where-Object { $_.Current.Name -eq 'Credit balance' })[0]
            if ($waiting.Count -gt 0 -or !$balance -or !$oldBalance -or
                ![Windows.Automation.Automation]::Compare($oldBalance,$balance)) { $reloaded = $true }
        }
        if (!$current -or !$reloaded) { continue }
        $texts = @((Controls $current ([Windows.Automation.ControlType]::Text)) | ForEach-Object { ($_.Current.Name -replace '[\u2018\u2019]', "'" -replace '\s+', ' ').Trim() })
        $pos = [array]::IndexOf($texts, 'Credit balance')
        if ($pos -lt 0 -or !($texts -ccontains $Organization)) { continue }
        $end = [Math]::Min($texts.Length - 1, $pos + 3)
        $amount = @($texts[($pos)..($end)] | Where-Object { $_ -match '^\$([0-9]+|[0-9]{1,3}(,[0-9]{3})+)\.\d{2}$' })
        if ($amount.Count -ne 1 -or !(IsBillingWindow $window)) { continue }
        $value = [decimal]::Parse($amount[0].Substring(1), [Globalization.CultureInfo]::InvariantCulture)
        $result = @{available=$value; at=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss+00:00')}
        break
    } catch [Windows.Automation.ElementNotAvailableException] { $reloaded = $true }
}
if (!$result) { throw 'No se pudo verificar un saldo nuevo para la cuenta indicada.' }
$dir = [IO.Path]::GetDirectoryName($OutputPath)
[IO.Directory]::CreateDirectory($dir) | Out-Null
$tmp = [IO.Path]::Combine($dir, [IO.Path]::GetRandomFileName())
try {
    [IO.File]::WriteAllText($tmp, ($result | ConvertTo-Json -Compress))
    if ([IO.File]::Exists($OutputPath)) { [IO.File]::Replace($tmp,$OutputPath,[System.Management.Automation.Language.NullString]::Value) }
    else { [IO.File]::Move($tmp,$OutputPath) }
} finally { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } }
