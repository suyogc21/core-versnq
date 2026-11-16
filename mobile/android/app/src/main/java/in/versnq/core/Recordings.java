package in.versnq.core;

import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Call recordings from the phone's own recorder (calls plan C4.3, the Runo model).
 *
 * The rep picks, once, the folder their phone's recorder saves calls to (Android's folder
 * picker; the app may read only that folder). After an answered call is in Core, the app waits
 * for the recorder's file: an audio file in that folder (or one level below) whose time matches
 * the call, preferring one whose name contains the number. It uploads it to that call. A call
 * whose recording doesn't turn up within 30 minutes is left without one; Core's company setting
 * "keep recordings" off means Core refuses it and the app forgets it.
 */
final class Recordings {

    static final String KEY_FOLDER = "recorder_folder";
    static final String KEY_PENDING = "pending_recordings";
    static final long MAX_BYTES = 50L * 1024 * 1024; // Core's limit
    private static final long WAIT_MS = 30 * 60 * 1000L;
    private static final long GIVE_UP_MS = 48 * 3600 * 1000L; // offline for two days: forget it
    private static final int MAX_PENDING = 200;
    private static final String[] AUDIO = { ".m4a", ".mp3", ".amr", ".aac", ".wav", ".ogg", ".opus", ".3gp", ".awb" };

    private Recordings() {}

    static Uri folder(Context context) {
        String uri = MainActivity.prefs(context).getString(KEY_FOLDER, null);
        return uri == null ? null : Uri.parse(uri);
    }

    /** A short name for the chosen folder, e.g. "Recordings/Call". */
    static String folderName(Context context) {
        Uri uri = folder(context);
        if (uri == null) return null;
        String id = DocumentsContract.getTreeDocumentId(uri);
        int colon = id.indexOf(':');
        return colon >= 0 ? id.substring(colon + 1) : id;
    }

    static JSONArray pending(SharedPreferences prefs) {
        try {
            return new JSONArray(prefs.getString(KEY_PENDING, "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    /** An answered call Core kept: wait for its recording. */
    static void queue(Context context, String callId, long startMs, long seconds, String number) {
        if (folder(context) == null) return;
        SharedPreferences prefs = MainActivity.prefs(context);
        JSONArray list = pending(prefs);
        try {
            JSONObject item = new JSONObject();
            item.put("call_id", callId);
            item.put("start", startMs);
            item.put("end", startMs + seconds * 1000L);
            item.put("digits", number == null ? "" : number.replaceAll("[^0-9]", ""));
            list.put(item);
        } catch (JSONException e) {
            return;
        }
        while (list.length() > MAX_PENDING) list.remove(0);
        prefs.edit().putString(KEY_PENDING, list.toString()).apply();
    }

    /** Uploads the recordings that have turned up. Returns false when Core can't be reached. */
    static boolean uploadPending(Context context, String base, String token) {
        Uri tree = folder(context);
        SharedPreferences prefs = MainActivity.prefs(context);
        JSONArray list = pending(prefs);
        if (tree == null || list.length() == 0) return true;
        List<Audio> files = list(context.getContentResolver(), tree);
        JSONArray keep = new JSONArray();
        boolean reachable = true;
        long now = System.currentTimeMillis();
        for (int i = 0; i < list.length(); i++) {
            JSONObject item = list.optJSONObject(i);
            if (item == null || now - item.optLong("end") > GIVE_UP_MS) continue;
            if (!reachable) {
                keep.put(item);
                continue;
            }
            long start = item.optLong("start");
            long end = item.optLong("end");
            Audio file = match(files, start, end, item.optString("digits"));
            if (file == null) {
                if (now - end < WAIT_MS) keep.put(item); // the recorder may still be saving
                continue;
            }
            int code = put(context.getContentResolver(), base + "/api/v1/calls/" + item.optString("call_id") + "/recording", token, file);
            if (code < 0 || code >= 500 || code == 429 || code == 401) {
                reachable = false;
                keep.put(item);
            }
            files.remove(file); // one recording, one call
        }
        prefs.edit().putString(KEY_PENDING, keep.toString()).apply();
        return reachable;
    }

    static final class Audio {
        Uri uri;
        String name;
        long modified;
        long size;
    }

    /** Audio files in the folder and one level of subfolders (recorders often use "Call"). */
    static List<Audio> list(ContentResolver resolver, Uri tree) {
        List<Audio> out = new ArrayList<>();
        List<String> folders = new ArrayList<>();
        try {
            String root = DocumentsContract.getTreeDocumentId(tree);
            collect(resolver, tree, root, out, folders);
            for (String sub : folders.subList(0, Math.min(folders.size(), 20))) {
                collect(resolver, tree, sub, out, null);
            }
        } catch (RuntimeException e) {
            // the folder was removed or access was taken away: no recordings
        }
        return out;
    }

    private static void collect(ContentResolver resolver, Uri tree, String docId, List<Audio> out, List<String> folders) {
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
        String[] cols = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED,
            DocumentsContract.Document.COLUMN_SIZE,
        };
        try (Cursor c = resolver.query(children, cols, null, null, null)) {
            while (c != null && c.moveToNext()) {
                String id = c.getString(0);
                String name = c.getString(1);
                String mime = c.getString(2);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    if (folders != null) folders.add(id);
                    continue;
                }
                if (name == null || !isAudio(name, mime)) continue;
                Audio a = new Audio();
                a.uri = DocumentsContract.buildDocumentUriUsingTree(tree, id);
                a.name = name;
                a.modified = c.isNull(3) ? 0 : c.getLong(3);
                a.size = c.isNull(4) ? 0 : c.getLong(4);
                if (a.size > 0 && a.size <= MAX_BYTES) out.add(a);
            }
        }
    }

    static boolean isAudio(String name, String mime) {
        if (mime != null && mime.startsWith("audio/")) return true;
        String lower = name.toLowerCase(Locale.ROOT);
        for (String ext : AUDIO) if (lower.endsWith(ext)) return true;
        return false;
    }

    /** The recording of a call: saved between a minute before it started and 10 minutes after
     * it ended; a name with the number wins, then the closest time to the call's end. */
    static Audio match(List<Audio> files, long start, long end, String digits) {
        String tail = digits.length() >= 7 ? digits.substring(digits.length() - 7) : null;
        Audio best = null;
        boolean bestNamed = false;
        long bestGap = Long.MAX_VALUE;
        for (Audio a : files) {
            if (a.modified < start - 60_000L || a.modified > end + 600_000L) continue;
            boolean named = tail != null && a.name.replaceAll("[^0-9]", "").contains(tail);
            long gap = Math.abs(a.modified - end);
            if (best == null || (named && !bestNamed) || (named == bestNamed && gap < bestGap)) {
                best = a;
                bestNamed = named;
                bestGap = gap;
            }
        }
        return best;
    }

    /** PUT the file as the body; the HTTP status, or -1 when Core can't be reached. */
    static int put(ContentResolver resolver, String url, String token, Audio file) {
        HttpURLConnection http = null;
        try (InputStream in = resolver.openInputStream(file.uri)) {
            if (in == null) return 404;
            http = (HttpURLConnection) new URL(url).openConnection();
            http.setConnectTimeout(15000);
            http.setReadTimeout(120000);
            http.setRequestMethod("PUT");
            http.setDoOutput(true);
            http.setInstanceFollowRedirects(false);
            http.setFixedLengthStreamingMode(file.size);
            http.setRequestProperty("Authorization", "Bearer " + token);
            http.setRequestProperty("Content-Type", "application/octet-stream");
            http.setRequestProperty("X-File-Name", file.name.replaceAll("[^\\x20-\\x7E]", "_"));
            http.setRequestProperty("User-Agent", MainActivity.USER_AGENT);
            try (OutputStream out = http.getOutputStream()) {
                byte[] buf = new byte[64 * 1024];
                int n;
                while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            }
            int code = http.getResponseCode();
            try (InputStream body = code < 400 ? http.getInputStream() : http.getErrorStream()) {
                if (body != null) while (body.read() != -1) {}
            }
            return code;
        } catch (SecurityException e) {
            return 403; // the folder can't be read any more: don't retry this file
        } catch (IOException e) {
            return -1;
        } finally {
            if (http != null) http.disconnect();
        }
    }
}
