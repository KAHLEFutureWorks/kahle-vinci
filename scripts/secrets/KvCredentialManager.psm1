Set-StrictMode -Version Latest

$script:DpapiSecretRoot = Join-Path $env:APPDATA "KAHLE-Vinci\secrets"

if (-not ("KahleVinci.CredentialManager" -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace KahleVinci {
  public static class CredentialManager {
    private const int CRED_TYPE_GENERIC = 1;
    private const int CRED_PERSIST_LOCAL_MACHINE = 2;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct CREDENTIAL {
      public UInt32 Flags;
      public UInt32 Type;
      public string TargetName;
      public string Comment;
      public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
      public UInt32 CredentialBlobSize;
      public IntPtr CredentialBlob;
      public UInt32 Persist;
      public UInt32 AttributeCount;
      public IntPtr Attributes;
      public string TargetAlias;
      public string UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWrite([In] ref CREDENTIAL userCredential, [In] UInt32 flags);

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(string target, UInt32 type, UInt32 reservedFlag, out IntPtr credentialPtr);

    [DllImport("advapi32.dll", EntryPoint = "CredFree", SetLastError = true)]
    private static extern void CredFree([In] IntPtr cred);

    public static void Write(string target, string secret, string userName) {
      byte[] secretBytes = Encoding.Unicode.GetBytes(secret ?? "");
      IntPtr blob = Marshal.AllocCoTaskMem(secretBytes.Length);
      try {
        Marshal.Copy(secretBytes, 0, blob, secretBytes.Length);
        CREDENTIAL credential = new CREDENTIAL();
        credential.Type = CRED_TYPE_GENERIC;
        credential.TargetName = target;
        credential.CredentialBlobSize = (UInt32)secretBytes.Length;
        credential.CredentialBlob = blob;
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE;
        credential.UserName = String.IsNullOrWhiteSpace(userName) ? Environment.UserName : userName;

        if (!CredWrite(ref credential, 0)) {
          throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        }
      } finally {
        Marshal.FreeCoTaskMem(blob);
      }
    }

    public static string Read(string target) {
      IntPtr credentialPtr;
      if (!CredRead(target, CRED_TYPE_GENERIC, 0, out credentialPtr)) {
        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
      }

      try {
        CREDENTIAL credential = (CREDENTIAL)Marshal.PtrToStructure(credentialPtr, typeof(CREDENTIAL));
        if (credential.CredentialBlob == IntPtr.Zero || credential.CredentialBlobSize == 0) {
          return "";
        }

        byte[] secretBytes = new byte[credential.CredentialBlobSize];
        Marshal.Copy(credential.CredentialBlob, secretBytes, 0, secretBytes.Length);
        return Encoding.Unicode.GetString(secretBytes).TrimEnd('\0');
      } finally {
        CredFree(credentialPtr);
      }
    }
  }
}
"@
}

function Get-KvCredentialTarget {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Prefix = "KAHLE-Vinci"
  )

  return "$Prefix/$Name"
}

function Get-KvSecretFilePath {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Prefix = "KAHLE-Vinci"
  )

  $target = Get-KvCredentialTarget -Name $Name -Prefix $Prefix
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($target)
    $hash = $sha.ComputeHash($bytes)
  } finally {
    $sha.Dispose()
  }
  $fileName = -join ($hash | ForEach-Object { $_.ToString("x2") })
  return Join-Path $script:DpapiSecretRoot "$fileName.dpapi"
}

function Set-KvDpapiSecret {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Secret,
    [string]$Prefix = "KAHLE-Vinci"
  )

  New-Item -ItemType Directory -Path $script:DpapiSecretRoot -Force | Out-Null
  $path = Get-KvSecretFilePath -Name $Name -Prefix $Prefix
  $secure = ConvertTo-SecureString -String $Secret -AsPlainText -Force
  $encrypted = ConvertFrom-SecureString -SecureString $secure
  Set-Content -Path $path -Value $encrypted -NoNewline -Encoding ASCII
}

function Get-KvDpapiSecret {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Prefix = "KAHLE-Vinci"
  )

  $path = Get-KvSecretFilePath -Name $Name -Prefix $Prefix
  if (-not (Test-Path -LiteralPath $path)) {
    return ""
  }

  $encrypted = Get-Content -LiteralPath $path -Raw
  if ([string]::IsNullOrWhiteSpace($encrypted)) {
    return ""
  }

  $secure = ConvertTo-SecureString -String $encrypted
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

function Set-KvCredential {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Secret,
    [string]$Prefix = "KAHLE-Vinci"
  )

  $target = Get-KvCredentialTarget -Name $Name -Prefix $Prefix
  try {
    [KahleVinci.CredentialManager]::Write($target, $Secret, $env:USERNAME)
    $fallbackPath = Get-KvSecretFilePath -Name $Name -Prefix $Prefix
    Remove-Item -LiteralPath $fallbackPath -ErrorAction SilentlyContinue
    return "Windows Credential Manager"
  } catch [System.ComponentModel.Win32Exception] {
    # Windows Generic Credentials have a small blob limit. Long API tokens are
    # stored outside the repo as DPAPI-protected current-user secrets instead.
    Set-KvDpapiSecret -Name $Name -Secret $Secret -Prefix $Prefix
    return "DPAPI file"
  }
}

function Get-KvCredential {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Prefix = "KAHLE-Vinci"
  )

  $target = Get-KvCredentialTarget -Name $Name -Prefix $Prefix
  try {
    return [KahleVinci.CredentialManager]::Read($target)
  } catch [System.ComponentModel.Win32Exception] {
    if ($_.Exception.NativeErrorCode -eq 1168) {
      return Get-KvDpapiSecret -Name $Name -Prefix $Prefix
    }
    $fallback = Get-KvDpapiSecret -Name $Name -Prefix $Prefix
    if (-not [string]::IsNullOrWhiteSpace($fallback)) {
      return $fallback
    }
    throw
  }
}

Export-ModuleMember -Function Get-KvCredentialTarget, Set-KvCredential, Get-KvCredential
