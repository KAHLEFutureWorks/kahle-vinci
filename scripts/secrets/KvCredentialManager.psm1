Set-StrictMode -Version Latest

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

function Set-KvCredential {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Secret,
    [string]$Prefix = "KAHLE-Vinci"
  )

  $target = Get-KvCredentialTarget -Name $Name -Prefix $Prefix
  [KahleVinci.CredentialManager]::Write($target, $Secret, $env:USERNAME)
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
      return ""
    }
    throw
  }
}

Export-ModuleMember -Function Get-KvCredentialTarget, Set-KvCredential, Get-KvCredential
