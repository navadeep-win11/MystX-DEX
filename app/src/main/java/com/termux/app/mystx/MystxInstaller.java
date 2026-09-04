package com.termux.app.mystx;

import android.content.Context;
import android.system.Os;

import com.termux.shared.logger.Logger;
import com.termux.shared.termux.TermuxConstants;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Installer for MystX DEX CLI and Web GUI runtime assets.
 */
public class MystxInstaller {

    private static final String LOG_TAG = "MystxInstaller";
    private static final String ASSET_BASE = "mystx";

    public static void installIfNeeded(final Context context) {
        new Thread(() -> {
            try {
                install(context);
            } catch (Exception e) {
                Logger.logStackTraceWithMessage(LOG_TAG, "Failed to install MystX assets", e);
            }
        }).start();
    }

    public static synchronized void install(Context context) throws IOException {
        Logger.logInfo(LOG_TAG, "Installing MystX DEX CLI, Web GUI and environment configurations...");

        File binDir = TermuxConstants.TERMUX_BIN_PREFIX_DIR;
        File shareDir = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "share/mystx");
        File homeMystxDir = new File(TermuxConstants.TERMUX_HOME_DIR_PATH, ".mystx");

        // 1. Copy CLI script
        if (binDir.exists()) {
            copyAssetToFile(context, ASSET_BASE + "/mystx_cli.sh", new File(binDir, "mystx"), true);
        }

        if (homeMystxDir.exists() || homeMystxDir.mkdirs()) {
            copyAssetToFile(context, ASSET_BASE + "/mystx_cli.sh", new File(homeMystxDir, "mystx"), true);
        }

        // 2. Copy shared web assets
        copyAssetDir(context, ASSET_BASE, shareDir);
        copyAssetDir(context, ASSET_BASE, homeMystxDir);

        // 3. Setup apt and dpkg environment directories
        ensureAptAndDpkgDirs(context);

        // 4. Setup apt.conf for com.mystx.dex
        setupAptConfig();

        // 5. Setup shell profile scripts (~/.bashrc, ~/.bash_profile, etc/profile.d/mystx-env.sh)
        setupShellProfiles();

        // 6. Setup am wrapper
        setupAmWrapper();

        // 7. Setup PRoot
        setupProot(context);

        Logger.logInfo(LOG_TAG, "MystX DEX assets and configs installed successfully.");
    }

    private static void ensureAptAndDpkgDirs(Context context) {
        try {
            new File(context.getCacheDir(), "apt/archives/partial").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "var/lib/apt/lists/partial").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "var/lib/dpkg/updates").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "var/lib/dpkg/info").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "var/log/apt").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "etc/apt/apt.conf.d").mkdirs();
            new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "etc/apt/sources.list.d").mkdirs();

            File statusFile = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "var/lib/dpkg/status");
            if (!statusFile.exists()) {
                File parent = statusFile.getParentFile();
                if (parent != null && !parent.exists()) parent.mkdirs();
                //noinspection ResultOfMethodCallIgnored
                statusFile.createNewFile();
            }
        } catch (Exception e) {
            Logger.logStackTraceWithMessage(LOG_TAG, "Failed creating apt/dpkg directories", e);
        }
    }

    private static void setupAptConfig() {
        try {
            File aptConf = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "etc/apt/apt.conf");
            File parent = aptConf.getParentFile();
            if (parent != null && !parent.exists()) parent.mkdirs();

            String config = "Dir \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/\";\n" +
                "Dir::State \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/var/lib/apt\";\n" +
                "Dir::State::status \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/var/lib/dpkg/status\";\n" +
                "Dir::Cache \"" + TermuxConstants.TERMUX_INTERNAL_PRIVATE_APP_DATA_DIR_PATH + "/cache/apt\";\n" +
                "Dir::Etc \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/etc/apt\";\n" +
                "Dir::Bin::methods \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/lib/apt/methods\";\n" +
                "Dir::Bin::dpkg \"" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/bin/dpkg\";\n" +
                "DPkg::Options {\n" +
                "    \"--admindir=" + TermuxConstants.TERMUX_PREFIX_DIR_PATH + "/var/lib/dpkg\";\n" +
                "};\n";

            try (FileOutputStream fos = new FileOutputStream(aptConf)) {
                fos.write(config.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
        } catch (Exception e) {
            Logger.logStackTraceWithMessage(LOG_TAG, "Failed writing apt.conf", e);
        }
    }

    private static void setupShellProfiles() {
        try {
            String profileContent = "# MystX DEX Login Profile\n" +
                "if [ -f \"$PREFIX/etc/profile\" ]; then\n" +
                "    . \"$PREFIX/etc/profile\"\n" +
                "fi\n";

            File bashProfile = new File(TermuxConstants.TERMUX_HOME_DIR_PATH, ".bash_profile");
            if (!bashProfile.exists()) {
                try (FileOutputStream fos = new FileOutputStream(bashProfile)) {
                    fos.write(profileContent.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                }
            }

            File bashrc = new File(TermuxConstants.TERMUX_HOME_DIR_PATH, ".bashrc");
            if (!bashrc.exists()) {
                try (FileOutputStream fos = new FileOutputStream(bashrc)) {
                    fos.write(profileContent.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                }
            }

            File profileD = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "etc/profile.d");
            if (!profileD.exists()) profileD.mkdirs();

            File envScript = new File(profileD, "mystx-env.sh");
            String envScriptContent = "#!/data/data/com.mystx.dex/files/usr/bin/sh\n" +
                "export SSL_CERT_FILE=\"$PREFIX/etc/tls/cert.pem\"\n" +
                "export CURL_CA_BUNDLE=\"$PREFIX/etc/tls/cert.pem\"\n" +
                "export TERMINFO=\"$PREFIX/share/terminfo\"\n" +
                "export TERMINFO_DIRS=\"$PREFIX/share/terminfo\"\n" +
                "export APT_CONFIG=\"$PREFIX/etc/apt/apt.conf\"\n" +
                "export DPKG_ADMINDIR=\"$PREFIX/var/lib/dpkg\"\n" +
                "export PYTHONHOME=\"$PREFIX\"\n";

            try (FileOutputStream fos = new FileOutputStream(envScript)) {
                fos.write(envScriptContent.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
            try {
                //noinspection OctalInteger
                Os.chmod(envScript.getAbsolutePath(), 0755);
            } catch (Exception ignored) {}

        } catch (Exception e) {
            Logger.logStackTraceWithMessage(LOG_TAG, "Failed writing shell profile scripts", e);
        }
    }

    private static void setupAmWrapper() {
        try {
            File amFile = new File(TermuxConstants.TERMUX_BIN_PREFIX_DIR, "am");
            String amContent = "#!/data/data/com.mystx.dex/files/usr/bin/sh\n" +
                "if [ -x \"/data/data/com.mystx.dex/files/usr/bin/termux-am\" ]; then\n" +
                "    exec /data/data/com.mystx.dex/files/usr/bin/termux-am \"$@\"\n" +
                "fi\n" +
                "exec /system/bin/app_process -Xnoimage-dex2oat / com.termux.termuxam.Am \"$@\"\n";

            try (FileOutputStream fos = new FileOutputStream(amFile)) {
                fos.write(amContent.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
            try {
                //noinspection OctalInteger
                Os.chmod(amFile.getAbsolutePath(), 0755);
            } catch (Exception ignored) {}
        } catch (Exception e) {
            Logger.logStackTraceWithMessage(LOG_TAG, "Failed creating am wrapper", e);
        }
    }

    private static void setupProot(Context context) {
        String abi = android.os.Build.SUPPORTED_ABIS[0];
        String arch;
        if (abi.startsWith("arm64") || abi.startsWith("aarch64")) {
            arch = "aarch64";
        } else if (abi.startsWith("armeabi") || abi.startsWith("arm")) {
            arch = "arm";
        } else if (abi.startsWith("x86_64")) {
            arch = "x86_64";
        } else {
            arch = "i686";
        }
        
        try {
            File prootBin = new File(TermuxConstants.TERMUX_BIN_PREFIX_DIR, "proot");
            copyAssetToFile(context, ASSET_BASE + "/proot/" + arch + "/bin/proot", prootBin, true);
            
            File libexec = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "libexec/proot");
            if (!libexec.exists()) libexec.mkdirs();
            
            String[] loaders = context.getAssets().list(ASSET_BASE + "/proot/" + arch + "/libexec/proot");
            if (loaders != null) {
                for (String l : loaders) {
                    copyAssetToFile(context, ASSET_BASE + "/proot/" + arch + "/libexec/proot/" + l, new File(libexec, l), true);
                }
            }
        } catch (Exception e) {
            Logger.logStackTraceWithMessage(LOG_TAG, "Failed setting up PRoot", e);
        }
    }

    private static void copyAssetDir(Context context, String assetDir, File targetDir) {
        if (!targetDir.exists()) {
            targetDir.mkdirs();
        }

        try {
            String[] list = context.getAssets().list(assetDir);
            if (list == null || list.length == 0) {
                return;
            }

            for (String file : list) {
                String assetPath = assetDir + "/" + file;
                File targetFile = new File(targetDir, file);
                String[] subList = context.getAssets().list(assetPath);
                if (subList != null && subList.length > 0) {
                    copyAssetDir(context, assetPath, targetFile);
                } else {
                    boolean isExecutable = file.endsWith(".sh") || file.equals("mystx_cli.sh") || file.endsWith(".py");
                    copyAssetToFile(context, assetPath, targetFile, isExecutable);
                }
            }
        } catch (IOException e) {
            Logger.logError(LOG_TAG, "Failed copying asset dir " + assetDir + ": " + e.getMessage());
        }
    }

    private static void copyAssetToFile(Context context, String assetPath, File targetFile, boolean isExecutable) {
        try {
            File parent = targetFile.getParentFile();
            if (parent != null && !parent.exists()) {
                parent.mkdirs();
            }

            try (InputStream in = context.getAssets().open(assetPath);
                 OutputStream out = new FileOutputStream(targetFile)) {
                byte[] buf = new byte[8192];
                int len;
                while ((len = in.read(buf)) > 0) {
                    out.write(buf, 0, len);
                }
            }

            if (isExecutable) {
                try {
                    //noinspection OctalInteger
                    Os.chmod(targetFile.getAbsolutePath(), 0755);
                } catch (Exception e) {
                    targetFile.setExecutable(true, false);
                }
            }
        } catch (IOException e) {
            Logger.logError(LOG_TAG, "Error writing asset " + assetPath + " to " + targetFile.getAbsolutePath() + ": " + e.getMessage());
        }
    }
}
