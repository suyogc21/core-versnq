package in.versnq.core;

import android.Manifest;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
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
}
