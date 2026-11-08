using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    [CreateAssetMenu(fileName = "Apparel", menuName = "LiminalLabs/CharacterCustomizer/Apparel")]
    public class ApparelObj : ScriptableObject
    {
        [Tooltip("Unique, stable number for this apparel (1-255, 0 = unassigned). Assigned automatically when the " +
                 "asset is created and never reused; it survives renames, so anything that needs a compact " +
                 "reference to an apparel (save data, replication) can use it instead of the asset name. " +
                 "Tools/Character Customizer/Validate Apparel Ids reports duplicates and fills in gaps.")]
        public byte Id;

        [Tooltip("The apparel data for this ApparelOBJ. Copy directly from an scrObj_Apparel entry.")]
        public CC.scrObj_Apparel.Apparel Apparel;

        [Tooltip("If true, this item can be chosen in the character-creation / customizer screen. Uncheck " +
                 "for special items that should only be obtained during gameplay (e.g. a hazmat suit). The " +
                 "Game-Ready Showcase generator excludes items with this turned off.")]
        public bool UsableInCharacterCreator = true;

        [Tooltip("Bodies this Apparel is not offered on, by CharacterBodyRegistry Key (\"Male\", \"Female\"): it is left " +
                 "out of the customizer's and the game's apparel lists for a character with that body, for a garment " +
                 "that does not fit it yet. One already worn comes off. Empty = offered on every " +
                 "body. Baked into the apparel index (ApparelIndex.Entry.HiddenBodyMask), which warns about unknown keys.")]
        public string[] HiddenOnBodies = System.Array.Empty<string>();

        [Tooltip("Not done yet: still being made, so hidden from players on every body (customizer, the game's apparel " +
                 "lists, the store, which refuses to sell it) and taken off anyone wearing it. New apparel starts Not done " +
                 "(ApparelIdAssigner sets it with the first Id, and on a copy it renumbers); Tools/Character Customizer/Apparel Editor marks it done, " +
                 "with every body's version of it. Separate from Usable In Character Creator and Hidden On Bodies, the " +
                 "manual hiding. False on assets made before it existed, which are done.")]
        public bool NotDone;

        [Tooltip("If true, the scalp hair (hair tables not marked Facial Hair: the hairstyle) is hidden while this Apparel " +
                 "is equipped. For hats, helmets and hoods. Eyebrows and beards stay: see Disable Facial Hair.")]
        public bool DisableHair;

        [Tooltip("If true, the facial hair (hair tables marked Facial Hair: eyebrows, beards) is hidden while this " +
                 "Apparel is equipped. For something covering the face, like the hazmat hood; never for a hat.")]
        public bool DisableFacialHair;

        [Tooltip("Raises the character's root by this amount when equipped. Use for shoes with heels or thick soles. Leave at 0 for no offset.")]
        public float VerticalOffset = 0f;

        [Tooltip("The slots this Apparel occupies. Add multiple for items that cover several slots, like a full suit.")]
        public ApparelSlot[] Slots;

        [Tooltip("Slots this Apparel visually suppresses while equipped. Items in these slots stay equipped (buffs still apply, save state preserved) but their meshes are hidden and their body masks are overridden by this apparel's mask. Use for a hazmat suit worn over normal clothes — list the slots it visually covers (e.g. Upper, Lower, Shoes).")]
        public ApparelSlot[] SuppressesSlots;

        public CharacterBuff[] buffs;

        /// <summary>The slot whose mesh and mask stand for this item: its first one, or -1 when it has none.</summary>
        public int PrimarySlot => Slots != null && Slots.Length > 0 ? (int)Slots[0] : -1;

        /// <summary>
        /// Where <paramref name="look"/> keeps this item's name, colourway and tint (ApparelNames, ApparelMaterials,
        /// ApparelTints): the first ApparelNames entry naming it, otherwise for a creator garment its slot's customizer
        /// tab (<see cref="ApparelLookWriter.CustomizerTabOf(ApparelSlot)"/>: the customizer saves those lists by tab,
        /// not by slot), otherwise -1. A run-only garment (UsableInCharacterCreator off: the Hazmat) has no place in a
        /// look, so it never reads another garment's colourway or tint (its slot's tab) nor overwrites one. The one rule
        /// for the player (CustomizableCharacterController) and Lite characters (CustomizableCharacterLite).
        /// </summary>
        public int LookIndexIn(CC.CC_CharacterData look)
        {
            var names = look?.ApparelNames;
            if (names != null)
            {
                for (int i = 0; i < names.Count; i++)
                {
                    if (names[i] == Apparel.Name || names[i] == name) return i;
                }
            }
            if (!UsableInCharacterCreator || PrimarySlot < 0) return -1;
            return ApparelLookWriter.CustomizerTabOf((ApparelSlot)PrimarySlot);
        }
    }


}
