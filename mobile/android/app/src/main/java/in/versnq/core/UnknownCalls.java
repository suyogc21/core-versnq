package in.versnq.core;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Calls with numbers Core doesn't know (Suyog, Nov 16): nothing is created by itself. The call
 * stays only on this phone until the rep says who it was: a new lead, an existing lead calling
 * from another number (the number is added to that lead), or personal (forgotten). Undecided
 * calls are forgotten after 7 days. One notification sums them up.
 */
final class UnknownCalls {

    static final String KEY = "unknown_calls";
    static final String CHANNEL = "unknown_calls";
    static final int NOTIFICATION_ID = 7002;
    static final long KEEP_MS = 7L * 24 * 3600 * 1000;
    private static final int MAX = 300;

    private UnknownCalls() {}

    static JSONArray list(Context context) {
        SharedPreferences prefs = MainActivity.prefs(context);
        JSONArray all;
        try {
            all = new JSONArray(prefs.getString(KEY, "[]"));
        } catch (JSONException e) {
            all = new JSONArray();
        }
        JSONArray fresh = new JSONArray();
        long now = System.currentTimeMillis();
        for (int i = 0; i < all.length(); i++) {
            JSONObject c = all.optJSONObject(i);
            if (c != null && now - c.optLong("date") < KEEP_MS) fresh.put(c);
        }
        if (fresh.length() != all.length()) save(context, fresh);
        return fresh;
    }

    private static void save(Context context, JSONArray list) {
        MainActivity.prefs(context).edit().putString(KEY, list.toString()).apply();
    }

    /** Keeps the call (the body Core would get) to ask about it. */
    static void add(Context context, JSONObject call, long date, long seconds) {
        JSONArray list = list(context);
        String id = call.optString("external_id");
        for (int i = 0; i < list.length(); i++) {
            if (id.equals(list.optJSONObject(i).optString("id"))) return; // already asked
        }
        try {
            JSONObject item = new JSONObject();
            item.put("id", id);
            item.put("date", date);
            item.put("seconds", seconds);
            item.put("number", call.optString("number"));
            item.put("direction", call.optString("direction"));
            item.put("status", call.optString("status"));
            item.put("call", call);
            list.put(item);
        } catch (JSONException e) {
            return;
        }
        while (list.length() > MAX) list.remove(0);
        save(context, list);
        notify(context, list.length());
    }

    static JSONObject take(Context context, String id) {
        JSONArray list = list(context);
        JSONArray keep = new JSONArray();
        JSONObject found = null;
        for (int i = 0; i < list.length(); i++) {
            JSONObject c = list.optJSONObject(i);
            if (id.equals(c.optString("id"))) found = c;
            else keep.put(c);
        }
        save(context, keep);
        notify(context, keep.length());
        return found;
    }

    static void notify(Context context, int count) {
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null) return;
        if (count == 0) {
            nm.cancel(NOTIFICATION_ID);
            return;
        }
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Calls not in Core", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Calls with numbers that aren't a lead yet: add them, or mark them personal");
            nm.createNotificationChannel(ch);
        }
        Intent open = new Intent(context, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(CallerPopup.EXTRA_OPEN, "/calls/unknown");
        PendingIntent tap = PendingIntent.getActivity(context, 1, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(context, CHANNEL) : new Notification.Builder(context);
        b.setSmallIcon(android.R.drawable.sym_call_outgoing)
            .setContentTitle(count == 1 ? "1 call isn't in Core" : count + " calls aren't in Core")
            .setContentText("Who was it? A new lead, a lead's other number, or personal")
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setContentIntent(tap);
        try {
            nm.notify(NOTIFICATION_ID, b.build());
        } catch (SecurityException e) {
            // notifications not allowed on this phone
        }
    }
}
