package in.versnq.core;

import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebView;
import androidx.activity.OnBackPressedCallback;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;

/**
 * Versnq Core for Android (calls plan, step C4).
 *
 * First launch: the app's own start page (www/index.html) asks for the company address.
 * After that the app opens that company's Core directly: the same screens and logins as the web.
 * Only that one address gets the native bridge (Capacitor injects it into the server URL only),
 * and only it may be navigated to inside the app; every other link opens outside the app.
 * versnq-core://reset (the offline page, or Core's "Use a different company") forgets the company.
 */
public class MainActivity extends BridgeActivity {

    static final String PREFS = "versnq";
    static final String BASE_DOMAIN = "core.versnq.in";
    static final String USER_AGENT = "VersnqCoreApp/" + BuildConfig.VERSION_NAME;

    static String companyHost(String slug) {
        return slug + "." + BASE_DOMAIN;
    }

    static SharedPreferences prefs(android.content.Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        registerPlugin(ShellPlugin.class);
        registerPlugin(PhonePlugin.class);
        String slug = prefs(this).getString("slug", null);
        if (slug != null && ShellPlugin.validSlug(slug)) {
            String host = companyHost(slug);
            config = new CapConfig.Builder(this)
                .setServerUrl("https://" + host)
                .setAllowNavigation(new String[] { host })
                .setErrorPath("error.html?core=" + Uri.encode("https://" + host))
                .setAppendedUserAgentString(USER_AGENT)
                .create();
        }
        super.onCreate(savedInstanceState);
        openFrom(getIntent());
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                back();
            }
        });
    }

    /** Android's back button: Core's page first (it closes an open menu or dialog), then the
     * page history, and on the first page the app goes to the background (it isn't closed). */
    private void back() {
        WebView web = getBridge() == null ? null : getBridge().getWebView();
        if (web == null) {
            moveTaskToBack(true);
            return;
        }
        web.evaluateJavascript("(function(){try{return !!(window.versnqBack&&window.versnqBack())}catch(e){return false}})()", handled -> {
            if ("true".equals(handled)) return;
            if (web.canGoBack()) web.goBack();
            else moveTaskToBack(true);
        });
    }

    /** Opening the app sends any calls not yet in Core (the background job does it otherwise). */
    @Override
    public void onResume() {
        super.onResume();
        if (prefs(this).getString(CallSync.KEY_TOKEN, null) != null) {
            final android.content.Context context = getApplicationContext();
            new Thread(() -> CallSync.run(context)).start();
            CallSyncJob.schedule(context);
        }
    }

    /** The caller popup was tapped: open that lead in the company's Core. */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        openFrom(intent);
    }

    private void openFrom(Intent intent) {
        String path = intent == null ? null : intent.getStringExtra(CallerPopup.EXTRA_OPEN);
        String slug = prefs(this).getString("slug", null);
        if (path == null || slug == null || !path.matches("^/leads/[0-9a-f-]{36}$") || getBridge() == null) return;
        intent.removeExtra(CallerPopup.EXTRA_OPEN);
        getBridge().getWebView().loadUrl("https://" + companyHost(slug) + path);
    }
}
