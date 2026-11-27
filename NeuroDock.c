#include <errno.h>
#include <fcntl.h>
#include <glib.h>
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define FULL_HEIGHT 46
#define HIDDEN_HEIGHT 4
#define ICON_SIZE 32
#define HIDE_DELAY_MS 4000

typedef struct {
    const char *name;
    const char *cmd;
    const char *icon_names[4];
    int clicks;
    GtkWidget *button;
} AppEntry;

typedef struct {
    GtkWidget *window;
    GtkWidget *box;
    GPtrArray *apps;
    char *data_path;
    char *backup_path;
    guint hide_timer_id;
    int panel_width;
    gboolean is_hidden;
} DockApp;

static AppEntry *create_default_apps(void) {
    AppEntry *list = g_new0(AppEntry, 9);

    list[0] = (AppEntry){"Firefox", "firefox", {"firefox", "browser", NULL}, 0, NULL};
    list[1] = (AppEntry){"GIMP", "gimp", {"gimp", NULL}, 0, NULL};
    list[2] = (AppEntry){"Word", "libreoffice --writer", {"libreoffice-writer", NULL}, 0, NULL};
    list[3] = (AppEntry){"Inkscape", "inkscape", {"inkscape", "org.inkscape.Inkscape", NULL}, 0, NULL};
    list[4] = (AppEntry){"Sublime", "subl", {"sublime-text", "subl", NULL}, 0, NULL};
    list[5] = (AppEntry){"Terminal", "gnome-terminal", {"utilities-terminal", "terminal", NULL}, 0, NULL};
    list[6] = (AppEntry){"File Manager", "thunar", {"system-file-manager", "thunar", "org.xfce.thunar", NULL}, 0, NULL};
    list[7] = (AppEntry){"LibreOffice", "libreoffice", {"libreoffice-startcenter", NULL}, 0, NULL};
    list[8] = (AppEntry){"Draw", "libreoffice --draw", {"libreoffice-draw", NULL}, 0, NULL};

    return list;
}

static gboolean write_atomic_file(const char *target_path, const char *content) {
    char *tmp_path = g_strdup_printf("%s.%ld.tmp", target_path, (long)getpid());
    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        g_warning("Failed to open temp file %s: %s", tmp_path, g_strerror(errno));
        g_free(tmp_path);
        return FALSE;
    }

    size_t len = strlen(content);
    size_t written = 0;
    while (written < len) {
        ssize_t n = write(fd, content + written, len - written);
        if (n < 0) {
            if (errno == EINTR) continue;
            g_warning("Write error to %s: %s", tmp_path, g_strerror(errno));
            close(fd);
            unlink(tmp_path);
            g_free(tmp_path);
            return FALSE;
        }
        written += (size_t)n;
    }

    fsync(fd);
    close(fd);

    if (rename(tmp_path, target_path) != 0) {
        g_warning("Failed to replace %s: %s", target_path, g_strerror(errno));
        unlink(tmp_path);
        g_free(tmp_path);
        return FALSE;
    }

    g_free(tmp_path);
    return TRUE;
}

static gboolean parse_clicks_json(const char *raw_json, GHashTable *out_map) {
    if (!raw_json || !*raw_json) return FALSE;

    GError *error = NULL;
    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, raw_json, -1, &error)) {
        g_clear_error(&error);
        g_object_unref(parser);
        return FALSE;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (!JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return FALSE;
    }

    JsonObject *obj = json_node_get_object(root);
    GList *members = json_object_get_members(obj);
    for (GList *l = members; l != NULL; l = l->next) {
        const char *key = (const char *)l->data;
        JsonNode *val_node = json_object_get_member(obj, key);
        if (JSON_NODE_HOLDS_VALUE(val_node) && json_node_get_value_type(val_node) == G_TYPE_INT64) {
            gint64 val = json_node_get_int(val_node);
            if (val >= 0 && val <= G_MAXINT) {
                g_hash_table_insert(out_map, g_strdup(key), GINT_TO_POINTER((int)val));
            }
        }
    }

    g_list_free(members);
    g_object_unref(parser);
    return TRUE;
}

static char *build_clicks_json(DockApp *dock) {
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);

    for (guint i = 0; i < dock->apps->len; i++) {
        AppEntry *app = g_ptr_array_index(dock->apps, i);
        json_builder_set_member_name(builder, app->name);
        json_builder_add_int_value(builder, app->clicks);
    }

    json_builder_end_object(builder);
    JsonGenerator *gen = json_generator_new();
    json_generator_set_pretty(gen, TRUE);
    JsonNode *root = json_builder_get_root(builder);
    json_generator_set_root(gen, root);
    char *result = json_generator_to_data(gen, NULL);

    json_node_unref(root);
    g_object_unref(gen);
    g_object_unref(builder);
    return result;
}

static void save_clicks(DockApp *dock, gboolean make_backup) {
    char *serialized = build_clicks_json(dock);
    if (!serialized) return;

    if (make_backup && g_file_test(dock->data_path, G_FILE_TEST_EXISTS)) {
        char *current = NULL;
        if (g_file_get_contents(dock->data_path, &current, NULL, NULL)) {
            GHashTable *check_map = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
            if (parse_clicks_json(current, check_map)) {
                write_atomic_file(dock->backup_path, current);
            }
            g_hash_table_destroy(check_map);
            g_free(current);
        }
    }

    write_atomic_file(dock->data_path, serialized);
    g_free(serialized);
}

static void apply_clicks_map(DockApp *dock, GHashTable *map) {
    for (guint i = 0; i < dock->apps->len; i++) {
        AppEntry *app = g_ptr_array_index(dock->apps, i);
        gpointer found;
        if (g_hash_table_lookup_extended(map, app->name, NULL, &found)) {
            app->clicks = GPOINTER_TO_INT(found);
        }
    }
}

static void load_clicks(DockApp *dock) {
    const char *candidates[2] = {dock->data_path, dock->backup_path};

    for (int i = 0; i < 2; i++) {
        const char *path = candidates[i];
        if (!g_file_test(path, G_FILE_TEST_EXISTS)) continue;

        char *content = NULL;
        if (g_file_get_contents(path, &content, NULL, NULL)) {
            GHashTable *map = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
            if (parse_clicks_json(content, map)) {
                apply_clicks_map(dock, map);
                g_hash_table_destroy(map);
                g_free(content);
                if (i == 1) {
                    save_clicks(dock, FALSE);
                }
                return;
            }
            g_hash_table_destroy(map);
            g_free(content);
        }
    }
}

static GtkWidget *create_app_icon_widget(const AppEntry *app) {
    GtkIconTheme *theme = gtk_icon_theme_get_default();
    for (int i = 0; app->icon_names[i] != NULL; i++) {
        GError *error = NULL;
        GdkPixbuf *pixbuf = gtk_icon_theme_load_icon(
            theme,
            app->icon_names[i],
            ICON_SIZE,
            GTK_ICON_LOOKUP_FORCE_SIZE,
            &error
        );
        if (pixbuf) {
            GtkWidget *img = gtk_image_new_from_pixbuf(pixbuf);
            g_object_unref(pixbuf);
            return img;
        }
        g_clear_error(&error);
    }

    const char *fallback_dirs[] = {
        "/usr/share/icons/Yaru/48x48/apps",
        "/usr/share/icons/hicolor/48x48/apps",
        "/usr/share/pixmaps",
        NULL
    };
    const char *exts[] = {".png", ".xpm", NULL};

    for (int i = 0; app->icon_names[i] != NULL; i++) {
        for (int d = 0; fallback_dirs[d] != NULL; d++) {
            for (int e = 0; exts[e] != NULL; e++) {
                char *path = g_strdup_printf("%s/%s%s", fallback_dirs[d], app->icon_names[i], exts[e]);
                if (g_file_test(path, G_FILE_TEST_EXISTS)) {
                    GError *err = NULL;
                    GdkPixbuf *pb = gdk_pixbuf_new_from_file_at_scale(path, ICON_SIZE, ICON_SIZE, TRUE, &err);
                    g_free(path);
                    if (pb) {
                        GtkWidget *img = gtk_image_new_from_pixbuf(pb);
                        g_object_unref(pb);
                        return img;
                    }
                    g_clear_error(&err);
                } else {
                    g_free(path);
                }
            }
        }
    }

    return gtk_image_new_from_icon_name("application-x-executable", GTK_ICON_SIZE_LARGE_TOOLBAR);
}

static void setup_dock_css(GtkWidget *window) {
    GtkCssProvider *provider = gtk_css_provider_new();
    const char *css =
        "window.dock-strip {"
        "  background-color: rgba(211, 211, 211, 0.85);"
        "  border-radius: 3px 3px 0 0;"
        "  min-height: 0;"
        "  min-width: 0;"
        "  padding: 0;"
        "  margin: 0;"
        "}";
    gtk_css_provider_load_from_data(provider, css, -1, NULL);
    GtkStyleContext *ctx = gtk_widget_get_style_context(window);
    gtk_style_context_add_provider(ctx, GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_object_unref(provider);
}

static void apply_panel_state(DockApp *dock, gboolean hidden) {
    dock->is_hidden = hidden;
    int height = hidden ? HIDDEN_HEIGHT : FULL_HEIGHT;
    int width = hidden ? (dock->panel_width / 2 > 140 ? dock->panel_width / 2 : 140) : dock->panel_width;

    GtkStyleContext *ctx = gtk_widget_get_style_context(dock->window);
    if (hidden) {
        gtk_widget_hide(dock->box);
        gtk_style_context_add_class(ctx, "dock-strip");
    } else {
        gtk_style_context_remove_class(ctx, "dock-strip");
        gtk_widget_show(dock->box);
    }

    GdkDisplay *display = gtk_widget_get_display(dock->window);
    GdkMonitor *monitor = display ? gdk_display_get_primary_monitor(display) : NULL;
    if (!monitor && display && gdk_display_get_n_monitors(display) > 0) {
        monitor = gdk_display_get_monitor(display, 0);
    }

    GdkRectangle geom = {0};
    if (monitor) {
        gdk_monitor_get_geometry(monitor, &geom);
    }
    if (geom.width <= 0) geom.width = 1920;
    if (geom.height <= 0) geom.height = 1080;

    if (width > geom.width) width = geom.width;
    int x = geom.x + (geom.width - width) / 2;
    int y = geom.y + geom.height - height;

    gtk_widget_set_size_request(dock->window, width, height);
    gtk_window_resize(GTK_WINDOW(dock->window), width, height);
    gtk_window_move(GTK_WINDOW(dock->window), x, y);
    if (gtk_widget_get_window(dock->window)) {
        gdk_window_move_resize(gtk_widget_get_window(dock->window), x, y, width, height);
        gdk_window_raise(gtk_widget_get_window(dock->window));
    }
}

static gboolean on_map_event(GtkWidget *widget, GdkEventAny *event, gpointer user_data) {
    (void)widget;
    (void)event;
    DockApp *dock = (DockApp *)user_data;
    apply_panel_state(dock, dock->is_hidden);
    return FALSE;
}

static gboolean hide_panel_cb(gpointer user_data) {
    DockApp *dock = (DockApp *)user_data;
    dock->hide_timer_id = 0;

    GdkDisplay *display = gdk_display_get_default();
    GdkSeat *seat = display ? gdk_display_get_default_seat(display) : NULL;
    GdkDevice *pointer = seat ? gdk_seat_get_pointer(seat) : NULL;

    if (pointer) {
        int px = 0, py = 0;
        gdk_device_get_position(pointer, NULL, &px, &py);

        int wx = 0, wy = 0, ww = 0, wh = 0;
        gtk_window_get_position(GTK_WINDOW(dock->window), &wx, &wy);
        gtk_window_get_size(GTK_WINDOW(dock->window), &ww, &wh);

        if (px >= wx && px <= wx + ww && py >= wy && py <= wy + wh) {
            dock->hide_timer_id = g_timeout_add(HIDE_DELAY_MS, hide_panel_cb, dock);
            return G_SOURCE_REMOVE;
        }
    }

    apply_panel_state(dock, TRUE);
    return G_SOURCE_REMOVE;
}

static void show_panel_now(DockApp *dock) {
    if (dock->hide_timer_id > 0) {
        g_source_remove(dock->hide_timer_id);
        dock->hide_timer_id = 0;
    }
    apply_panel_state(dock, FALSE);
}

static gboolean on_enter_notify(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data) {
    (void)widget;
    (void)event;
    show_panel_now((DockApp *)user_data);
    return FALSE;
}

static gboolean on_leave_notify(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data) {
    (void)widget;
    (void)event;
    DockApp *dock = (DockApp *)user_data;
    if (dock->hide_timer_id > 0) {
        g_source_remove(dock->hide_timer_id);
    }
    dock->hide_timer_id = g_timeout_add(HIDE_DELAY_MS, hide_panel_cb, dock);
    return FALSE;
}

static void launch_detached(const char *cmd) {
    GError *error = NULL;
    gchar **argv = NULL;
    if (!g_shell_parse_argv(cmd, NULL, &argv, &error)) {
        g_warning("Failed to parse command '%s': %s", cmd, error ? error->message : "unknown");
        g_clear_error(&error);
        return;
    }

    GSubprocessLauncher *launcher = g_subprocess_launcher_new(G_SUBPROCESS_FLAGS_NONE);
    g_subprocess_launcher_set_flags(launcher, G_SUBPROCESS_FLAGS_NONE);

    GSubprocess *proc = g_subprocess_launcher_spawnv(launcher, (const gchar *const *)argv, &error);
    if (!proc) {
        g_warning("Failed to launch '%s': %s", cmd, error ? error->message : "unknown");
        g_clear_error(&error);
    } else {
        g_object_unref(proc);
    }

    g_object_unref(launcher);
    g_strfreev(argv);
}

static gint compare_apps_by_clicks(gconstpointer a, gconstpointer b) {
    const AppEntry *app_a = *(const AppEntry *const *)a;
    const AppEntry *app_b = *(const AppEntry *const *)b;
    if (app_b->clicks != app_a->clicks) {
        return (app_b->clicks > app_a->clicks) ? 1 : -1;
    }
    return g_strcmp0(app_a->name, app_b->name);
}

static void rebuild_dock_ui(DockApp *dock);

typedef struct {
    DockApp *dock;
    AppEntry *app;
} AppActionCtx;

static void on_reset_clicks(GtkMenuItem *item, gpointer user_data) {
    (void)item;
    AppActionCtx *ctx = (AppActionCtx *)user_data;
    ctx->app->clicks = 0;
    save_clicks(ctx->dock, TRUE);
    rebuild_dock_ui(ctx->dock);
    show_panel_now(ctx->dock);
}

static void on_quit_dock(GtkMenuItem *item, gpointer user_data) {
    (void)item;
    gtk_main_quit();
    (void)user_data;
}

static gboolean on_button_press(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    (void)widget;
    AppActionCtx *ctx = (AppActionCtx *)user_data;

    if (event->type == GDK_BUTTON_PRESS && event->button == 3) {
        GtkWidget *menu = gtk_menu_new();

        char *info_label = g_strdup_printf("%s (clicks: %d)", ctx->app->name, ctx->app->clicks);
        GtkWidget *info_item = gtk_menu_item_new_with_label(info_label);
        gtk_widget_set_sensitive(info_item, FALSE);
        gtk_menu_shell_append(GTK_MENU_SHELL(menu), info_item);
        g_free(info_label);

        GtkWidget *reset_item = gtk_menu_item_new_with_label("Reset counter");
        g_signal_connect(reset_item, "activate", G_CALLBACK(on_reset_clicks), ctx);
        gtk_menu_shell_append(GTK_MENU_SHELL(menu), reset_item);

        GtkWidget *sep = gtk_separator_menu_item_new();
        gtk_menu_shell_append(GTK_MENU_SHELL(menu), sep);

        GtkWidget *quit_item = gtk_menu_item_new_with_label("Quit dock");
        g_signal_connect(quit_item, "activate", G_CALLBACK(on_quit_dock), ctx->dock);
        gtk_menu_shell_append(GTK_MENU_SHELL(menu), quit_item);

        gtk_widget_show_all(menu);
        gtk_menu_popup_at_pointer(GTK_MENU(menu), (const GdkEvent *)event);
        return TRUE;
    }

    return FALSE;
}

static void on_app_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    AppActionCtx *ctx = (AppActionCtx *)user_data;
    ctx->app->clicks += 1;
    save_clicks(ctx->dock, TRUE);
    launch_detached(ctx->app->cmd);
    rebuild_dock_ui(ctx->dock);
    show_panel_now(ctx->dock);
}

static void clear_container_cb(GtkWidget *widget, gpointer user_data) {
    (void)user_data;
    gtk_widget_destroy(widget);
}

static void rebuild_dock_ui(DockApp *dock) {
    g_ptr_array_sort(dock->apps, compare_apps_by_clicks);
    gtk_container_foreach(GTK_CONTAINER(dock->box), clear_container_cb, NULL);

    for (guint i = 0; i < dock->apps->len; i++) {
        AppEntry *app = g_ptr_array_index(dock->apps, i);
        GtkWidget *btn = gtk_button_new();
        GtkWidget *icon = create_app_icon_widget(app);
        gtk_container_add(GTK_CONTAINER(btn), icon);
        gtk_widget_set_tooltip_text(btn, app->name);

        AppActionCtx *ctx = g_new0(AppActionCtx, 1);
        ctx->dock = dock;
        ctx->app = app;
        g_object_set_data_full(G_OBJECT(btn), "action-ctx", ctx, g_free);

        g_signal_connect(btn, "clicked", G_CALLBACK(on_app_clicked), ctx);
        g_signal_connect(btn, "button-press-event", G_CALLBACK(on_button_press), ctx);

        gtk_box_pack_start(GTK_BOX(dock->box), btn, FALSE, FALSE, 2);
        app->button = btn;
    }

    gtk_widget_show_all(dock->box);

    GtkRequisition min_req = {0}, nat_req = {0};
    gtk_widget_get_preferred_size(dock->box, &min_req, &nat_req);
    dock->panel_width = (nat_req.width + 16 > 120) ? (nat_req.width + 16) : 120;
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);

    char *exe_path = g_file_read_link("/proc/self/exe", NULL);
    char *base_dir = exe_path ? g_path_get_dirname(exe_path) : g_get_current_dir();
    g_free(exe_path);

    DockApp dock = {0};
    dock.data_path = g_build_filename(base_dir, "dock_clicks.json", NULL);
    dock.backup_path = g_build_filename(base_dir, "dock_clicks.json.bak", NULL);
    dock.panel_width = 300;
    dock.apps = g_ptr_array_new();

    AppEntry *raw_apps = create_default_apps();
    for (int i = 0; i < 9; i++) {
        g_ptr_array_add(dock.apps, &raw_apps[i]);
    }

    load_clicks(&dock);

    dock.window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_type_hint(GTK_WINDOW(dock.window), GDK_WINDOW_TYPE_HINT_DOCK);
    gtk_window_set_decorated(GTK_WINDOW(dock.window), FALSE);
    gtk_window_set_keep_above(GTK_WINDOW(dock.window), TRUE);
    gtk_window_set_skip_taskbar_hint(GTK_WINDOW(dock.window), TRUE);
    gtk_window_set_skip_pager_hint(GTK_WINDOW(dock.window), TRUE);
    gtk_widget_add_events(dock.window, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
    setup_dock_css(dock.window);

    dock.box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 2);
    gtk_container_set_border_width(GTK_CONTAINER(dock.box), 2);
    gtk_container_add(GTK_CONTAINER(dock.window), dock.box);

    g_signal_connect(dock.window, "enter-notify-event", G_CALLBACK(on_enter_notify), &dock);
    g_signal_connect(dock.window, "leave-notify-event", G_CALLBACK(on_leave_notify), &dock);
    g_signal_connect(dock.window, "map-event", G_CALLBACK(on_map_event), &dock);
    g_signal_connect(dock.window, "destroy", G_CALLBACK(gtk_main_quit), NULL);

    rebuild_dock_ui(&dock);
    gtk_widget_show_all(dock.window);
    apply_panel_state(&dock, TRUE);

    gtk_main();

    g_ptr_array_free(dock.apps, TRUE);
    g_free(raw_apps);
    g_free(dock.data_path);
    g_free(dock.backup_path);
    g_free(base_dir);

    return 0;
}
