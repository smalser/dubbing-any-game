param([Parameter(Mandatory=$true)][string]$ManagedRoot, [Parameter(Mandatory=$true)][string]$LoaderRoot, [Parameter(Mandatory=$true)][string]$Dotnet, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$managed = (Resolve-Path -LiteralPath $ManagedRoot).Path
$sdk = & $Dotnet --list-sdks | Select-Object -Last 1
if (!$sdk) { throw 'A .NET SDK is required, not just a runtime' }
$sdkVersion = ($sdk -split ' ')[0]
$sdkRoot = [regex]::Match($sdk,'\[(.*)\]').Groups[1].Value
$compiler = Join-Path $sdkRoot "$sdkVersion/Roslyn/bincore/csc.dll"
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$refs = @('netstandard.dll','mscorlib.dll','System.dll','System.Core.dll','UnityEngine.dll','UnityEngine.CoreModule.dll','Newtonsoft.Json.dll','FMODUnity.dll') | ForEach-Object { '/reference:'+(Join-Path $managed $_) }
$refs += @('BepInEx.dll','0Harmony.dll') | ForEach-Object { '/reference:'+(Join-Path $LoaderRoot "BepInEx/core/$_") }
& $Dotnet $compiler /nologo /target:library /nostdlib /langversion:7.3 /optimize+ "/out:$Output/UniversalDubbing.Fmod.dll" $refs (Join-Path $PSScriptRoot 'Plugin.cs') (Join-Path $PSScriptRoot 'OverrideService.cs') (Join-Path $PSScriptRoot 'Manifest.cs') (Join-Path $PSScriptRoot 'OverrideLifecycle.cs')
if ($LASTEXITCODE -ne 0) { throw 'C# compilation failed' }
Get-FileHash -LiteralPath "$Output/UniversalDubbing.Fmod.dll" -Algorithm SHA256
