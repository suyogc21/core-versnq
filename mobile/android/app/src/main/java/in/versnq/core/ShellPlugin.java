package in.versnq.core;

import android.net.Uri;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.regex.Pattern;

/** The app shell: which company this phone opens. */
@CapacitorPlugin(name = "VersnqShell")
public class ShellPlugin extends Plugin {

    private static final Pattern SLUG = Pattern.compile("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$");

    static boolean validSlug(String slug) {
        return slug != null && SLUG.matcher(slug).matches();
    }

    @PluginMethod
    public void setCompany(PluginCall call) {
        String slug = call.getString("slug", "");
        if (!validSlug(slug)) {
            call.reject("Type just the first part of the address, like acme.");
            return;
        }
        MainActivity.prefs(getContext()).edit().putString("slug", slug).apply();
        call.resolve();
        getActivity().runOnUiThread(() -> getActivity().recreate());
    }

    @PluginMethod
    public void info(PluginCall call) {
        JSObject out = new JSObject();
        out.put("version", BuildConfig.VERSION_NAME);
        out.put("company", MainActivity.prefs(getContext()).getString("slug", null));
        call.resolve(out);
    }

    /** versnq-core://reset: forget the company and show the start page again. */
    @Override
    public Boolean shouldOverrideLoad(Uri url) {
        if ("versnq-core".equals(url.getScheme())) {
            if ("reset".equals(url.getHost())) {
                MainActivity.prefs(getContext()).edit().remove("slug").apply();
                getActivity().runOnUiThread(() -> getActivity().recreate());
            }
            return true;
        }
        return null;
    }
}
