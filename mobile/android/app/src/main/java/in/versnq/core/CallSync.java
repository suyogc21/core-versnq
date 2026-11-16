package in.versnq.core;

import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.provider.CallLog;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import org.json.JSONObject;

/**
 * Sends the rep's calls from the phone's call log to Core (calls plan C4.2).
 *
 * The call log itself is the queue: the app remembers the time of the last call Core accepted
 * and, each run, sends every newer call in order, with the call log's own id as external_id, so
 * Core never logs a call twice. No internet: nothing advances and the next run sends it.
 * Core keeps only calls with a lead's number (the company's own rule); others are dropped there.
 * Answered calls Core kept then wait for their recording (Recordings, C4.3).
 */
final class CallSync {

    static final String KEY_TOKEN = "phone_token";
    static final String KEY_CURSOR = "calls_after";
    static final String KEY_LAST_SYNC = "last_sync_at";
    static final String KEY_LAST_ERROR = "last_error";
    private static final int BATCH = 50;
    private static final Object LOCK = new Object();

    private CallSync() {}

    static final class Result {
        int sent;
        String error; // null when everything due was sent
    }

    static Result run(Context context) {
        synchronized (LOCK) {
            Result result = new Result();
            SharedPreferences prefs = MainActivity.prefs(context);
            String token = prefs.getString(KEY_TOKEN, null);
            String slug = prefs.getString("slug", null);
            if (token == null || slug == null) {
                result.error = "not_connected";
                return result;
            }
            if (!PhonePlugin.hasCallLogPermission(context)) {
                result.error = "no_permission";
                save(prefs, result);
                return result;
            }
            long after = prefs.getLong(KEY_CURSOR, System.currentTimeMillis());
            String base = "https://" + MainActivity.companyHost(slug);
            String[] columns = {
                CallLog.Calls._ID, CallLog.Calls.NUMBER, CallLog.Calls.TYPE, CallLog.Calls.DATE, CallLog.Calls.DURATION
            };
            try (
                Cursor c = context
                    .getContentResolver()
                    .query(
                        CallLog.Calls.CONTENT_URI,
                        columns,
                        CallLog.Calls.DATE + " > ?",
                        new String[] { String.valueOf(after) },
                        CallLog.Calls.DATE + " ASC"
                    )
            ) {
                while (c != null && c.moveToNext() && result.sent < BATCH) {
                    long id = c.getLong(0);
                    String number = c.getString(1);
                    int type = c.getInt(2);
                    long date = c.getLong(3);
                    long seconds = c.getLong(4);
                    JSONObject body = toCall(id, number, type, date, seconds);
                    if (body != null) {
                        Response r = post(base + "/api/v1/calls", token, body);
                        int code = r.code;
                        if (code == 401) {
                            result.error = "signed_out"; // the phone was removed in Core
                            break;
                        }
                        if (code < 0 || code >= 500 || code == 429) {
                            result.error = "offline"; // try again on the next run
                            break;
                        }
                        result.sent++; // 2xx, or a call Core can't take (4xx): don't retry it
                        if (code < 300 && r.json != null && !r.json.optBoolean("tracked", true)) {
                            UnknownCalls.add(context, body, date, seconds); // ask who it was
                        }
                        JSONObject kept = r.json == null ? null : r.json.optJSONObject("call");
                        if (code < 300 && kept != null && "answered".equals(kept.optString("status"))) {
                            Recordings.queue(context, kept.optString("id"), date, seconds, number);
                        }
                    }
                    after = date;
                    prefs.edit().putLong(KEY_CURSOR, after).apply();
                }
            } catch (SecurityException e) {
                result.error = "no_permission";
            }
            if (result.error == null && !Recordings.uploadPending(context, base, token)) {
                result.error = "offline";
            }
            save(prefs, result);
            return result;
        }
    }

    private static void save(SharedPreferences prefs, Result result) {
        prefs
            .edit()
            .putLong(KEY_LAST_SYNC, System.currentTimeMillis())
            .putString(KEY_LAST_ERROR, result.error)
            .apply();
    }

    /** One call-log row as Core's call, or null for rows that aren't a call with someone. */
    static JSONObject toCall(long id, String number, int type, long date, long seconds) {
        String direction;
        String status;
        switch (type) {
            case CallLog.Calls.INCOMING_TYPE:
                direction = "in";
                status = seconds > 0 ? "answered" : "missed";
                break;
            case CallLog.Calls.OUTGOING_TYPE:
                direction = "out";
                status = seconds > 0 ? "answered" : "no_answer";
                break;
            case CallLog.Calls.MISSED_TYPE:
            case CallLog.Calls.REJECTED_TYPE:
                direction = "in";
                status = "missed";
                break;
            default: // voicemail, blocked, answered on another device
                return null;
        }
        if (number == null || number.replaceAll("[^0-9]", "").length() < 3) {
            return null; // a private or unknown number
        }
        SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        iso.setTimeZone(TimeZone.getTimeZone("UTC"));
        try {
            JSONObject body = new JSONObject();
            body.put("external_id", "log-" + id + "-" + date);
            body.put("direction", direction);
            body.put("status", status);
            body.put("number", number);
            body.put("started_at", iso.format(new Date(date)));
            body.put("duration_seconds", status.equals("answered") ? Math.min(seconds, 86400) : 0);
            return body;
        } catch (org.json.JSONException e) {
            return null;
        }
    }

    static final class Response {
        int code; // -1 when Core can't be reached
        JSONObject json;
    }

    /** POST JSON with the phone key. */
    static Response post(String url, String token, JSONObject body) {
        Response res = new Response();
        res.code = -1;
        HttpURLConnection http = null;
        try {
            http = (HttpURLConnection) new URL(url).openConnection();
            http.setConnectTimeout(15000);
            http.setReadTimeout(30000);
            http.setRequestMethod("POST");
            http.setDoOutput(true);
            http.setInstanceFollowRedirects(false);
            http.setRequestProperty("Authorization", "Bearer " + token);
            http.setRequestProperty("Content-Type", "application/json");
            http.setRequestProperty("User-Agent", MainActivity.USER_AGENT);
            try (OutputStream out = http.getOutputStream()) {
                out.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            res.code = http.getResponseCode();
            try (InputStream in = res.code < 400 ? http.getInputStream() : http.getErrorStream()) {
                if (in != null) {
                    java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
                    byte[] chunk = new byte[8192];
                    int n;
                    while ((n = in.read(chunk)) != -1 && buf.size() < 1_000_000) buf.write(chunk, 0, n);
                    try {
                        res.json = new JSONObject(buf.toString("UTF-8"));
                    } catch (org.json.JSONException e) {
                        res.json = null;
                    }
                }
            }
            return res;
        } catch (IOException e) {
            return res;
        } finally {
            if (http != null) http.disconnect();
        }
    }
}
