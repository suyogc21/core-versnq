package in.versnq.core;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import java.util.UUID;

/**
 * The phone part, as Core's page inside the app sees it (calls plan C4.2): call-log permission,
 * connecting the phone key Core gave the signed-in rep, and the sync status.
 * Only the company's own Core address gets this bridge (see MainActivity).
 */
@CapacitorPlugin(
    name = "VersnqPhone",
    permissions = { @Permission(alias = "calls", strings = { Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_PHONE_STATE }) }
)
public class PhonePlugin extends Plugin {

    static boolean hasCallLogPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED;
    }

    static String installId(Context context) {
        SharedPreferences prefs = MainActivity.prefs(context);
        String id = prefs.getString("install_id", null);
        if (id == null) {
            id = UUID.randomUUID().toString().replace("-", "");
            prefs.edit().putString("install_id", id).apply();
        }
        return id;
    }

    private JSObject status() {
        Context context = getContext();
        SharedPreferences prefs = MainActivity.prefs(context);
        JSObject out = new JSObject();
        out.put("installId", installId(context));
        out.put("device", Build.MANUFACTURER + " " + Build.MODEL);
        out.put("version", BuildConfig.VERSION_NAME);
        out.put("android", Build.VERSION.RELEASE);
        out.put("permission", getPermissionState("calls") == PermissionState.GRANTED);
        out.put("connected", prefs.getString(CallSync.KEY_TOKEN, null) != null);
        long last = prefs.getLong(CallSync.KEY_LAST_SYNC, 0);
        if (last > 0) out.put("lastSyncAt", last);
        out.put("lastError", prefs.getString(CallSync.KEY_LAST_ERROR, null));
        out.put("folder", Recordings.folderName(context));
        out.put("pendingRecordings", Recordings.pending(prefs).length());
        return out;
    }

    @PluginMethod
    public void info(PluginCall call) {
        call.resolve(status());
    }

    @PluginMethod
    public void requestCallPermission(PluginCall call) {
        if (getPermissionState("calls") == PermissionState.GRANTED) {
            call.resolve(status());
        } else {
            requestPermissionForAlias("calls", call, "afterPermission");
        }
    }

    @PermissionCallback
    private void afterPermission(PluginCall call) {
        call.resolve(status());
    }

    /** Keeps the phone key Core gave this rep and starts sending calls from now on. */
    @PluginMethod
    public void connect(PluginCall call) {
        String token = call.getString("token", "");
        if (token == null || !token.startsWith("vq_app_") || token.length() > 200) {
            call.reject("That isn't a phone key from Core");
            return;
        }
        Context context = getContext();
        SharedPreferences prefs = MainActivity.prefs(context);
        SharedPreferences.Editor edit = prefs.edit().putString(CallSync.KEY_TOKEN, token).remove(CallSync.KEY_LAST_ERROR);
        if (!prefs.contains(CallSync.KEY_CURSOR)) {
            edit.putLong(CallSync.KEY_CURSOR, System.currentTimeMillis()); // calls from now on, never history
        }
        edit.apply();
        CallSyncJob.schedule(context);
        call.resolve(status());
    }

    @PluginMethod
    public void disconnect(PluginCall call) {
        Context context = getContext();
        MainActivity.prefs(context).edit().remove(CallSync.KEY_TOKEN).remove(CallSync.KEY_LAST_ERROR).apply();
        CallSyncJob.cancel(context);
        call.resolve(status());
    }

    /** Sends any calls not yet in Core, now. */
    @PluginMethod
    public void syncNow(PluginCall call) {
        Context context = getContext();
        new Thread(() -> {
            CallSync.Result result = CallSync.run(context);
            JSObject out = status();
            out.put("sent", result.sent);
            call.resolve(out);
        }).start();
    }

    /** Recordings (C4.3): the rep picks the folder their phone's recorder saves calls to. */
    @PluginMethod
    public void pickRecordingFolder(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(call, intent, "folderPicked");
    }

    @ActivityCallback
    private void folderPicked(PluginCall call, ActivityResult result) {
        if (call == null) return;
        Intent data = result.getData();
        Uri uri = data == null ? null : data.getData();
        if (uri == null) {
            call.resolve(status()); // the rep went back without choosing
            return;
        }
        Context context = getContext();
        try {
            context.getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (SecurityException e) {
            call.reject("Android didn't allow reading that folder. Choose it again.");
            return;
        }
        MainActivity.prefs(context).edit().putString(Recordings.KEY_FOLDER, uri.toString()).apply();
        JSObject out = status();
        out.put("recordingsFound", Recordings.list(context.getContentResolver(), uri).size());
        call.resolve(out);
    }

    @PluginMethod
    public void forgetRecordingFolder(PluginCall call) {
        Context context = getContext();
        Uri uri = Recordings.folder(context);
        if (uri != null) {
            try {
                context.getContentResolver().releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (SecurityException e) {
                // already gone
            }
        }
        MainActivity.prefs(context).edit().remove(Recordings.KEY_FOLDER).remove(Recordings.KEY_PENDING).apply();
        call.resolve(status());
    }
}
