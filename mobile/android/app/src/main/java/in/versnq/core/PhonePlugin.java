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
    permissions = {
        @Permission(alias = "calls", strings = { Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_PHONE_STATE }),
        @Permission(alias = "notify", strings = { Manifest.permission.POST_NOTIFICATIONS }),
        @Permission(alias = "dial", strings = { Manifest.permission.CALL_PHONE }),
    }
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
            // the caller popup is a notification, so ask for that too (Android 13+)
            String[] aliases = Build.VERSION.SDK_INT >= 33 ? new String[] { "calls", "notify" } : new String[] { "calls" };
            requestPermissionForAliases(aliases, call, "afterPermission");
        }
    }

    @PermissionCallback
    private void afterPermission(PluginCall call) {
        call.resolve(status());
    }

    /** The dialer (Nov 17): calls the number from the rep's own SIM straight away. The first time
     * Android asks the rep to allow it; without that, the phone's dialer opens with the number
     * (one more tap). The call log then sends the call to Core as any other call. */
    @PluginMethod
    public void dial(PluginCall call) {
        String number = call.getString("number", "");
        if (number == null || !number.matches("\\+?[0-9]{4,16}")) {
            call.reject("That isn't a phone number");
            return;
        }
        if (getPermissionState("dial") == PermissionState.GRANTED) {
            placeCall(call);
        } else {
            requestPermissionForAlias("dial", call, "afterDialPermission");
        }
    }

    @PermissionCallback
    private void afterDialPermission(PluginCall call) {
        placeCall(call);
    }

    private void placeCall(PluginCall call) {
        boolean direct = getPermissionState("dial") == PermissionState.GRANTED;
        Intent intent = new Intent(direct ? Intent.ACTION_CALL : Intent.ACTION_DIAL, Uri.parse("tel:" + call.getString("number")));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getContext().startActivity(intent);
        } catch (SecurityException | android.content.ActivityNotFoundException e) {
            call.reject("This phone can't place the call");
            return;
        }
        JSObject out = new JSObject();
        out.put("direct", direct);
        call.resolve(out);
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

    /** Calls with numbers Core doesn't know, waiting for the rep (newest first). */
    @PluginMethod
    public void unknownCalls(PluginCall call) {
        org.json.JSONArray list = UnknownCalls.list(getContext());
        com.getcapacitor.JSArray out = new com.getcapacitor.JSArray();
        for (int i = list.length() - 1; i >= 0; i--) {
            org.json.JSONObject c = list.optJSONObject(i);
            JSObject item = new JSObject();
            item.put("id", c.optString("id"));
            item.put("number", c.optString("number"));
            item.put("direction", c.optString("direction"));
            item.put("status", c.optString("status"));
            item.put("date", c.optLong("date"));
            item.put("seconds", c.optLong("seconds"));
            out.put(item);
        }
        JSObject res = new JSObject();
        res.put("calls", out);
        call.resolve(res);
    }

    /** The rep said who it was (a new lead was made, or the number added to a lead): send the
     * call again; Core now finds the lead by its number. */
    @PluginMethod
    public void sendUnknown(PluginCall call) {
        String id = call.getString("id", "");
        Context context = getContext();
        new Thread(() -> {
            org.json.JSONObject item = UnknownCalls.take(context, id);
            JSObject out = new JSObject();
            if (item == null) {
                out.put("tracked", false);
                call.resolve(out);
                return;
            }
            SharedPreferences prefs = MainActivity.prefs(context);
            String token = prefs.getString(CallSync.KEY_TOKEN, null);
            String slug = prefs.getString("slug", null);
            CallSync.Response r = token == null || slug == null ? null
                : CallSync.post("https://" + MainActivity.companyHost(slug) + "/api/v1/calls", token, item.optJSONObject("call"));
            boolean tracked = r != null && r.code < 300 && r.json != null && r.json.optBoolean("tracked");
            if (tracked) {
                org.json.JSONObject kept = r.json.optJSONObject("call");
                if (kept != null && "answered".equals(kept.optString("status"))) {
                    Recordings.queue(context, kept.optString("id"), item.optLong("date"), item.optLong("seconds"), item.optString("number"));
                    Recordings.uploadPending(context, "https://" + MainActivity.companyHost(slug), token);
                }
            } else {
                UnknownCalls.add(context, item.optJSONObject("call"), item.optLong("date"), item.optLong("seconds"));
            }
            out.put("tracked", tracked);
            call.resolve(out);
        }).start();
    }

    /** Personal: forgotten on this phone; Core never gets it. */
    @PluginMethod
    public void dismissUnknown(PluginCall call) {
        UnknownCalls.take(getContext(), call.getString("id", ""));
        call.resolve();
    }
}
