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
        Logger.logInfo(LOG_TAG, "Installing MystX DEX CLI and Web GUI assets...");

        File binDir = TermuxConstants.TERMUX_BIN_PREFIX_DIR;
        File shareDir = new File(TermuxConstants.TERMUX_PREFIX_DIR_PATH, "share/mystx");
        File homeMystxDir = new File(TermuxConstants.TERMUX_HOME_DIR_PATH, ".mystx");

        if (binDir.exists()) {
            copyAssetToFile(context, ASSET_BASE + "/mystx_cli.sh", new File(binDir, "mystx"), true);
        }

        if (homeMystxDir.exists() || homeMystxDir.mkdirs()) {
            copyAssetToFile(context, ASSET_BASE + "/mystx_cli.sh", new File(homeMystxDir, "mystx"), true);
        }

        copyAssetDir(context, ASSET_BASE, shareDir);
        copyAssetDir(context, ASSET_BASE, homeMystxDir);

        Logger.logInfo(LOG_TAG, "MystX DEX assets installed successfully.");
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
