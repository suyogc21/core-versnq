package in.versnq.core;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.telephony.TelephonyManager;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONObject;

/**
 * The caller popup (calls plan C4.4): while the phone rings, a notification says which lead is
 * calling ("Asha Rao is calling · Lead · Qualified · owner Ravi"); tapping it opens the lead.
 * Core answers only for leads this rep may see; the number isn't stored. Android still delivers
 * the phone-state broadcast to apps that aren't open (it's on Android's list of exceptions), and
 * includes the number when the app may read the call log.
 */
public class CallerPopup extends BroadcastReceiver {

    static final String CHANNEL = "callers";
    static final int NOTIFICATION_ID = 7001;
    static final String EXTRA_OPEN = "in.versnq.core.OPEN";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!TelephonyManager.ACTION_PHONE_STATE_CHANGED.equals(intent.getAction())) return;
        String state = intent.getStringExtra(TelephonyManager.EXTRA_STATE);
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null) return;
        if (!TelephonyManager.EXTRA_STATE_RINGING.equals(state)) {
            nm.cancel(NOTIFICATION_ID); // answered or ended: the popup goes
            return;
        }
        @SuppressWarnings("deprecation")
        String number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER);
        SharedPreferences prefs = MainActivity.prefs(context);
        String token = prefs.getString(CallSync.KEY_TOKEN, null);
        String slug = prefs.getString("slug", null);
        if (number == null || token == null || slug == null) return; // the broadcast also comes once without the number
        final PendingResult pending = goAsync();
        final Context app = context.getApplicationContext();
        new Thread(() -> {
            try {
                JSONObject lead = lookup("https://" + MainActivity.companyHost(slug), token, number);
                if (lead != null) show(app, nm, slug, lead);
            } finally {
                pending.finish();
            }
        }).start();
    }

    private static JSONObject lookup(String base, String token, String number) {
        HttpURLConnection http = null;
        try {
            http = (HttpURLConnection) new URL(base + "/api/v1/phone/lookup?number=" + Uri.encode(number)).openConnection();
            http.setConnectTimeout(5000);
            http.setReadTimeout(5000);
            http.setInstanceFollowRedirects(false);
            http.setRequestProperty("Authorization", "Bearer " + token);
            http.setRequestProperty("User-Agent", MainActivity.USER_AGENT);
            if (http.getResponseCode() != 200) return null;
            try (InputStream in = http.getInputStream()) {
                java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
                byte[] chunk = new byte[4096];
                int n;
                while ((n = in.read(chunk)) != -1 && buf.size() < 100_000) buf.write(chunk, 0, n);
                String text = buf.toString("UTF-8").trim();
                return text.equals("null") ? null : new JSONObject(text);
            }
        } catch (IOException | org.json.JSONException e) {
            return null;
        } finally {
            if (http != null) http.disconnect();
        }
    }

    private static void show(Context context, NotificationManager nm, String slug, JSONObject lead) {
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Who's calling", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Shows which lead is calling while the phone rings");
            ch.setSound(null, null); // the phone is already ringing
            nm.createNotificationChannel(ch);
        }
        StringBuilder text = new StringBuilder("Lead");
        if (!lead.optString("stage").isEmpty() && !lead.isNull("stage")) text.append(" · ").append(lead.optString("stage"));
        if (lead.optBoolean("is_yours")) text.append(" · yours");
        else if (!lead.isNull("owner_name")) text.append(" · owner ").append(lead.optString("owner_name"));
        Intent open = new Intent(context, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(EXTRA_OPEN, "/leads/" + lead.optString("lead_id"));
        PendingIntent tap = PendingIntent.getActivity(
            context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(context, CHANNEL) : new Notification.Builder(context);
        b.setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle(lead.optString("name") + " is calling")
            .setContentText(text.toString())
            .setCategory(Notification.CATEGORY_CALL)
            .setPriority(Notification.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(tap);
        try {
            nm.notify(NOTIFICATION_ID, b.build());
        } catch (SecurityException e) {
            // notifications not allowed on this phone
        }
    }
}
