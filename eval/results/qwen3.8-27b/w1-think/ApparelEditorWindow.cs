// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private List<ApparelObj> allApparel = new List<ApparelObj>();
        private List<ApparelObj> shownApparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private ApparelObj selected;
        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex;
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private bool needsReload;
        private Editor cachedEditor;

        // Lazy one-time styles
        private GUIStyle notDoneTagStyle;
        private GUIStyle hiddenTagStyle;
        private string[] slotOptions;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            LoadAssets();
        }

        private void OnDisable()
        {
            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void OnProjectChange()
        {
            needsReload = true;
            Repaint();
        }

        private void OnGUI()
        {
            if (needsReload)
            {
                LoadAssets();
                needsReload = false;
            }

            RebuildShownList();
            HandleKeyboardNav();
            DrawToolbar();
            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        // ─── Loading ───────────────────────────────────────────────────────────

        private void LoadAssets()
        {
            // Editor tooling: FindAssets is fine here.
            string[] guids = AssetDatabase.FindAssets("t:ApparelObj");
            ApparelObj previousSelected = selected;

            allApparel.Clear();
            byAssetName.Clear();

            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                ApparelObj asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (asset == null) continue;
                allApparel.Add(asset);
                byAssetName[asset.name] = asset;
            }

            allApparel.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            // Keep selection only if the asset still exists in the project
            if (previousSelected != null)
            {
                bool found = false;
                foreach (ApparelObj a in allApparel)
                {
                    if (a == previousSelected) { found = true; break; }
                }
                if (!found) selected = null;
            }
        }

        // ─── Filtering ─────────────────────────────────────────────────────────

        private void RebuildShownList()
        {
            shownApparel.Clear();

            ApparelSlot? slot = null;
            if (slotFilterIndex > 0)
            {
                string[] names = Enum.GetNames(typeof(ApparelSlot));
                if (slotFilterIndex - 1 < names.Length)
                    slot = (ApparelSlot)Enum.Parse(typeof(ApparelSlot), names[slotFilterIndex - 1]);
            }

            foreach (ApparelObj a in allApparel)
            {
                if (!MatchSearch(a)) continue;
                if (!MatchStatus(a)) continue;
                if (!MatchSlot(a, slot)) continue;
                shownApparel.Add(a);
            }
        }

        private bool MatchSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            if (a.name != null && a.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            string appName = a.Apparel.Name;
            if (appName != null && appName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            string display = a.Apparel.DisplayName;
            if (display != null && display.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            return false;
        }

        private bool MatchStatus(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.NotDone:
                    return a.NotDone;
                case StatusFilter.Done:
                    return !a.NotDone;
                case StatusFilter.ManuallyHidden:
                    return !a.NotDone && IsManuallyHidden(a);
                default:
                    return true;
            }
        }

        private bool MatchSlot(ApparelObj a, ApparelSlot? slot)
        {
            if (slot == null) return true;
            if (a.Slots == null) return false;
            for (int i = 0; i < a.Slots.Length; i++)
                if (a.Slots[i] == slot.Value) return true;
            return false;
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.UsableInCharacterCreator || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0);
        }

        // ─── Keyboard navigation ───────────────────────────────────────────────

        private void HandleKeyboardNav()
        {
            if (shownApparel.Count == 0) return;
            if (Event.current.type != EventType.KeyDown) return;
            if (Event.current.keyCode != KeyCode.UpArrow && Event.current.keyCode != KeyCode.DownArrow) return;

            int idx = 0;
            for (int i = 0; i < shownApparel.Count; i++)
            {
                if (shownApparel[i] == selected) { idx = i; break; }
            }

            if (Event.current.keyCode == KeyCode.UpArrow)
                idx = Mathf.Max(0, idx - 1);
            else
                idx = Mathf.Min(shownApparel.Count - 1, idx + 1);

            selected = shownApparel[idx];
            Event.current.Use();
        }

        // ─── Toolbar ───────────────────────────────────────────────────────────

        private void DrawToolbar()
        {
            bool anyNotDoneShown = false;
            foreach (ApparelObj a in shownApparel)
            {
                if (a.NotDone) { anyNotDoneShown = true; break; }
            }

            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, GetSlotOptions(), EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();
            GUILayout.Label(shownApparel.Count + " of " + allApparel.Count, EditorStyles.miniLabel);

            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    int count = 0;
                    foreach (ApparelObj a in shownApparel)
                        if (a.NotDone) count++;

                    if (count > 0 && EditorUtility.DisplayDialog(
                            "Mark apparel done",
                            "Mark " + count + " apparel done? They become visible to players.",
                            "Mark done", "Cancel"))
                    {
                        MarkDone(EnumerateNotDoneShown(), byAssetName);
                        RebuildShownList();
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
                LoadAssets();

            EditorGUILayout.EndHorizontal();
        }

        private IEnumerable<ApparelObj> EnumerateNotDoneShown()
        {
            foreach (ApparelObj a in shownApparel)
                if (a.NotDone) yield return a;
        }

        // ─── List (left pane) ──────────────────────────────────────────────────

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shownApparel.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                for (int i = 0; i < shownApparel.Count; i++)
                {
                    ApparelObj apparel = shownApparel[i];
                    Rect row = EditorGUILayout.GetControlRect(false, 20);

                    if (apparel == selected)
                        EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

                    if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                    {
                        selected = apparel;
                        Event.current.Use();
                        GUI.FocusControl(null);
                    }

                    Rect nameRect = new Rect(row.x + 4f, row.y, row.width - 148f, row.height);
                    Rect slotRect = new Rect(row.x + row.width - 140f, row.y, 70f, row.height);
                    Rect tagRect = new Rect(row.x + row.width - 68f, row.y, 68f, row.height);

                    EditorGUI.LabelField(nameRect, apparel.name);

                    string slotText = (apparel.Slots != null && apparel.Slots.Length > 0)
                        ? apparel.Slots[0].ToString()
                        : "-";
                    EditorGUI.LabelField(slotRect, slotText, EditorStyles.miniLabel);

                    if (apparel.NotDone)
                    {
                        EditorGUI.LabelField(tagRect, "Not done", GetNotDoneStyle());
                    }
                    else if (IsManuallyHidden(apparel))
                    {
                        EditorGUI.LabelField(tagRect, "Hidden", GetHiddenStyle());
                    }
                }
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        // ─── Details (right pane) ──────────────────────────────────────────────

        private void DrawDetails()
        {
            EditorGUILayout.BeginVertical();
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                using (new EditorGUI.DisabledScope(true))
                {
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
                }

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox(
                        "Not done yet: hidden from players on every body and never sold. Mark it done to show it.",
                        MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        MarkDone(new[] { selected }, byAssetName);
                    }
                }
                else
                {
                    string msg = "Done: visible to players";
                    if (IsManuallyHidden(selected))
                        msg += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    EditorGUILayout.HelpBox(msg, MessageType.Info);
                }

                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Ping"))
                    EditorGUIUtility.PingObject(selected);
                if (GUILayout.Button("Select in Project"))
                    Selection.activeObject = selected;
                EditorGUILayout.EndHorizontal();

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                cachedEditor.OnInspectorGUI();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        // ─── Mark done (shared by both buttons) ────────────────────────────────

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            HashSet<ApparelObj> toMark = new HashSet<ApparelObj>();

            foreach (ApparelObj item in items)
            {
                toMark.Add(item);
                List<ApparelIndex.Entry> versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (ApparelIndex.Entry entry in versions)
                    {
                        if (entry.AssetName != null && byAssetName.TryGetValue(entry.AssetName, out ApparelObj version))
                            toMark.Add(version);
                    }
                }
            }

            List<string> markedNames = new List<string>();
            foreach (ApparelObj apparel in toMark)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                AssetDatabase.SaveAssetIfDirty(apparel);
                markedNames.Add(apparel.name);
            }

            if (markedNames.Count > 0)
                Debug.Log("[ApparelEditorWindow] Marked done: " + string.Join(", ", markedNames));
        }

        // ─── Lazy helpers ──────────────────────────────────────────────────────

        private string[] GetSlotOptions()
        {
            if (slotOptions != null) return slotOptions;
            string[] names = Enum.GetNames(typeof(ApparelSlot));
            slotOptions = new string[names.Length + 1];
            slotOptions[0] = "Any slot";
            for (int i = 0; i < names.Length; i++)
                slotOptions[i + 1] = names[i];
            return slotOptions;
        }

        private GUIStyle GetNotDoneStyle()
        {
            if (notDoneTagStyle == null)
            {
                notDoneTagStyle = new GUIStyle(EditorStyles.miniLabel)
                {
                    normal = { textColor = new Color(1f, 0.6f, 0.2f) },
                    alignment = TextAnchor.MiddleRight
                };
            }
            return notDoneTagStyle;
        }

        private GUIStyle GetHiddenStyle()
        {
            if (hiddenTagStyle == null)
            {
                hiddenTagStyle = new GUIStyle(EditorStyles.miniLabel)
                {
                    normal = { textColor = new Color(0.5f, 0.5f, 0.5f) },
                    alignment = TextAnchor.MiddleRight
                };
            }
            return hiddenTagStyle;
        }
    }
}
#endif
