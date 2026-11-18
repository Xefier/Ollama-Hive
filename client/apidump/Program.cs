// apidump <list file>
// Writes the public API of compiled .NET assemblies as JSON, for code_index.py. Each line of the list file is
// "<assembly path>\t<output path>". Reads metadata only (System.Reflection.Metadata): nothing is loaded or run, so
// Unity's and any other framework's assemblies can be read by this runtime.
//
// Output: {"asm": name, "types": [{"ns", "n" (Outer.Inner<T>), "k" (class|struct|interface|enum|delegate),
//          "h" (declaration line), "b" ([base and interface names]), "m": [[member name, signature], ...]}]}
// Only public and protected types and members; property and event accessors, operators, compiler-generated and
// [Obsolete] members are left out. Type names inside signatures are written without their namespace.

using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

sealed class GenericContext
{
    public string[] Type = Array.Empty<string>();
    public string[] Method = Array.Empty<string>();
}

sealed class Names : ISignatureTypeProvider<string, GenericContext>
{
    static readonly Regex Arity = new Regex(@"`\d+");

    public static string Strip(string name) => Arity.Replace(name, "");

    public string GetPrimitiveType(PrimitiveTypeCode code) => code switch
    {
        PrimitiveTypeCode.Boolean => "bool", PrimitiveTypeCode.Byte => "byte", PrimitiveTypeCode.SByte => "sbyte",
        PrimitiveTypeCode.Char => "char", PrimitiveTypeCode.Int16 => "short", PrimitiveTypeCode.UInt16 => "ushort",
        PrimitiveTypeCode.Int32 => "int", PrimitiveTypeCode.UInt32 => "uint", PrimitiveTypeCode.Int64 => "long",
        PrimitiveTypeCode.UInt64 => "ulong", PrimitiveTypeCode.Single => "float", PrimitiveTypeCode.Double => "double",
        PrimitiveTypeCode.String => "string", PrimitiveTypeCode.Object => "object", PrimitiveTypeCode.Void => "void",
        _ => code.ToString(),
    };

    public static string DefinitionName(MetadataReader reader, TypeDefinitionHandle handle)
    {
        var type = reader.GetTypeDefinition(handle);
        var name = reader.GetString(type.Name);
        var outer = type.GetDeclaringType();
        return outer.IsNil ? name : DefinitionName(reader, outer) + "." + name;
    }

    public string GetTypeFromDefinition(MetadataReader reader, TypeDefinitionHandle handle, byte rawTypeKind) =>
        Strip(DefinitionName(reader, handle));

    public static string ReferenceName(MetadataReader reader, TypeReferenceHandle handle)
    {
        var reference = reader.GetTypeReference(handle);
        var name = reader.GetString(reference.Name);
        return reference.ResolutionScope.Kind == HandleKind.TypeReference
            ? ReferenceName(reader, (TypeReferenceHandle)reference.ResolutionScope) + "." + name
            : name;
    }

    public string GetTypeFromReference(MetadataReader reader, TypeReferenceHandle handle, byte rawTypeKind) =>
        Strip(ReferenceName(reader, handle));

    public string GetTypeFromSpecification(MetadataReader reader, GenericContext context, TypeSpecificationHandle handle,
        byte rawTypeKind) => reader.GetTypeSpecification(handle).DecodeSignature(this, context);

    public string GetSZArrayType(string element) => element + "[]";
    public string GetArrayType(string element, ArrayShape shape) => element + "[" + new string(',', shape.Rank - 1) + "]";
    public string GetByReferenceType(string element) => "ref " + element;
    public string GetPointerType(string element) => element + "*";
    public string GetPinnedType(string element) => element;
    public string GetModifiedType(string modifier, string unmodified, bool isRequired) => unmodified;
    public string GetFunctionPointerType(MethodSignature<string> signature) => "delegate*";

    public string GetGenericInstantiation(string generic, ImmutableArray<string> arguments) =>
        generic == "Nullable" && arguments.Length == 1 ? arguments[0] + "?" : generic + "<" + string.Join(", ", arguments) + ">";

    public string GetGenericMethodParameter(GenericContext context, int index) =>
        index < context.Method.Length ? context.Method[index] : "TM" + index;

    public string GetGenericTypeParameter(GenericContext context, int index) =>
        index < context.Type.Length ? context.Type[index] : "T" + index;
}

static class Program
{
    static readonly Names Provider = new Names();

    static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.Error.WriteLine("usage: apidump <list file of \"assembly<TAB>output\" lines>");
            return 2;
        }
        int failed = 0;
        foreach (var line in File.ReadAllLines(args[0]))
        {
            var parts = line.Split('\t');
            if (parts.Length != 2)
                continue;
            object result;
            try
            {
                result = Dump(parts[0]);
            }
            catch (Exception error)
            {
                // A native library or a damaged file: an empty entry, so it is not tried again until it changes
                result = new Dictionary<string, object> { ["asm"] = Path.GetFileNameWithoutExtension(parts[0]),
                    ["error"] = error.GetType().Name + ": " + error.Message, ["types"] = new List<object>() };
                failed++;
            }
            File.WriteAllText(parts[1], JsonSerializer.Serialize(result), new UTF8Encoding(false));
        }
        Console.WriteLine("failed " + failed);
        return 0;
    }

    static string[] GenericNames(MetadataReader reader, GenericParameterHandleCollection handles) =>
        handles.Select(handle => reader.GetString(reader.GetGenericParameter(handle).Name)).ToArray();

    static bool HasAttribute(MetadataReader reader, CustomAttributeHandleCollection attributes, string name)
    {
        foreach (var handle in attributes)
        {
            var constructor = reader.GetCustomAttribute(handle).Constructor;
            string type = null;
            if (constructor.Kind == HandleKind.MemberReference)
            {
                var parent = reader.GetMemberReference((MemberReferenceHandle)constructor).Parent;
                if (parent.Kind == HandleKind.TypeReference)
                    type = reader.GetString(reader.GetTypeReference((TypeReferenceHandle)parent).Name);
                else if (parent.Kind == HandleKind.TypeDefinition)
                    type = reader.GetString(reader.GetTypeDefinition((TypeDefinitionHandle)parent).Name);
            }
            else if (constructor.Kind == HandleKind.MethodDefinition)
            {
                var parent = reader.GetMethodDefinition((MethodDefinitionHandle)constructor).GetDeclaringType();
                type = reader.GetString(reader.GetTypeDefinition(parent).Name);
            }
            if (type == name)
                return true;
        }
        return false;
    }

    static bool Visible(MetadataReader reader, TypeDefinitionHandle handle)
    {
        var type = reader.GetTypeDefinition(handle);
        switch (type.Attributes & TypeAttributes.VisibilityMask)
        {
            case TypeAttributes.Public:
                return true;
            case TypeAttributes.NestedPublic:
            case TypeAttributes.NestedFamily:
            case TypeAttributes.NestedFamORAssem:
                return Visible(reader, type.GetDeclaringType());
            default:
                return false;
        }
    }

    static string EntityName(MetadataReader reader, EntityHandle handle, GenericContext context)
    {
        switch (handle.Kind)
        {
            case HandleKind.TypeDefinition:
                return Provider.GetTypeFromDefinition(reader, (TypeDefinitionHandle)handle, 0);
            case HandleKind.TypeReference:
                return Provider.GetTypeFromReference(reader, (TypeReferenceHandle)handle, 0);
            case HandleKind.TypeSpecification:
                return Provider.GetTypeFromSpecification(reader, context, (TypeSpecificationHandle)handle, 0);
            default:
                return "";
        }
    }

    static string Access(MethodAttributes attributes)
    {
        switch (attributes & MethodAttributes.MemberAccessMask)
        {
            case MethodAttributes.Public: return "public";
            case MethodAttributes.Family:
            case MethodAttributes.FamORAssem: return "protected";
            default: return null;
        }
    }

    static string Access(FieldAttributes attributes)
    {
        switch (attributes & FieldAttributes.FieldAccessMask)
        {
            case FieldAttributes.Public: return "public";
            case FieldAttributes.Family:
            case FieldAttributes.FamORAssem: return "protected";
            default: return null;
        }
    }

    static string Modifiers(MethodAttributes attributes, bool isInterface)
    {
        if ((attributes & MethodAttributes.Static) != 0)
            return "static ";
        if (isInterface)
            return "";
        if ((attributes & MethodAttributes.Abstract) != 0)
            return "abstract ";
        if ((attributes & MethodAttributes.Virtual) != 0 && (attributes & MethodAttributes.Final) == 0)
            return (attributes & MethodAttributes.NewSlot) != 0 ? "virtual " : "override ";
        return "";
    }

    static string Parameters(MetadataReader reader, MethodDefinition method, MethodSignature<string> signature, bool extension)
    {
        var names = new string[signature.ParameterTypes.Length];
        var flags = new ParameterAttributes[signature.ParameterTypes.Length];
        var isParams = new bool[signature.ParameterTypes.Length];
        foreach (var handle in method.GetParameters())
        {
            var parameter = reader.GetParameter(handle);
            int at = parameter.SequenceNumber - 1;
            if (at < 0 || at >= names.Length)
                continue;
            names[at] = reader.GetString(parameter.Name);
            flags[at] = parameter.Attributes;
            isParams[at] = HasAttribute(reader, parameter.GetCustomAttributes(), "ParamArrayAttribute");
        }
        var parts = new List<string>();
        for (int at = 0; at < names.Length; at++)
        {
            var type = signature.ParameterTypes[at];
            if (type.StartsWith("ref ") && (flags[at] & ParameterAttributes.Out) != 0)
                type = "out " + type.Substring(4);
            else if (type.StartsWith("ref ") && (flags[at] & ParameterAttributes.In) != 0)
                type = "in " + type.Substring(4);
            var text = (at == 0 && extension ? "this " : "") + (isParams[at] ? "params " : "") + type + " " + (names[at] ?? "arg" + at);
            if ((flags[at] & ParameterAttributes.Optional) != 0 || (flags[at] & ParameterAttributes.HasDefault) != 0)
                text += " = default";
            parts.Add(text);
        }
        return string.Join(", ", parts);
    }

    static object Dump(string path)
    {
        using var stream = File.OpenRead(path);
        using var pe = new PEReader(stream);
        if (!pe.HasMetadata)
            throw new BadImageFormatException("no .NET metadata");
        var reader = pe.GetMetadataReader();
        var types = new List<object>();
        foreach (var handle in reader.TypeDefinitions)
        {
            if (!Visible(reader, handle))
                continue;
            var type = reader.GetTypeDefinition(handle);
            var rawName = reader.GetString(type.Name);
            if (rawName.StartsWith("<") || HasAttribute(reader, type.GetCustomAttributes(), "CompilerGeneratedAttribute")
                || HasAttribute(reader, type.GetCustomAttributes(), "ObsoleteAttribute"))
                continue;
            types.Add(DumpType(reader, handle, type));
        }
        var assembly = reader.IsAssembly ? reader.GetString(reader.GetAssemblyDefinition().Name) : Path.GetFileNameWithoutExtension(path);
        return new Dictionary<string, object> { ["asm"] = assembly, ["types"] = types };
    }

    static string Namespace(MetadataReader reader, TypeDefinitionHandle handle)
    {
        var type = reader.GetTypeDefinition(handle);
        var outer = type.GetDeclaringType();
        return outer.IsNil ? reader.GetString(type.Namespace) : Namespace(reader, outer);
    }

    static object DumpType(MetadataReader reader, TypeDefinitionHandle handle, TypeDefinition type)
    {
        var context = new GenericContext { Type = GenericNames(reader, type.GetGenericParameters()) };
        var name = Names.Strip(Names.DefinitionName(reader, handle));
        // A nested type's generic parameters include its outer type's: only its own count is known from the names,
        // so the whole list goes on the innermost name, which is right for every non-nested type
        var display = name + (context.Type.Length > 0 ? "<" + string.Join(", ", context.Type) + ">" : "");

        var baseName = type.BaseType.IsNil ? "" : EntityName(reader, type.BaseType, context);
        bool baseIsSystemObject = baseName == "Object" && type.BaseType.Kind == HandleKind.TypeReference
            && reader.GetString(reader.GetTypeReference((TypeReferenceHandle)type.BaseType).Namespace) == "System";
        bool isInterface = (type.Attributes & TypeAttributes.Interface) != 0;
        string kind = isInterface ? "interface" : baseName == "Enum" ? "enum" : baseName == "ValueType" ? "struct"
            : baseName == "MulticastDelegate" ? "delegate" : "class";
        var bases = new List<string>();
        if (kind == "class" && baseName != "" && baseName != "object" && !baseIsSystemObject)
            bases.Add(baseName);
        if (kind != "enum" && kind != "delegate")
            foreach (var implemented in type.GetInterfaceImplementations())
                bases.Add(EntityName(reader, reader.GetInterfaceImplementation(implemented).Interface, context));

        string modifiers = "";
        if (kind == "class")
        {
            bool isAbstract = (type.Attributes & TypeAttributes.Abstract) != 0, isSealed = (type.Attributes & TypeAttributes.Sealed) != 0;
            modifiers = isAbstract && isSealed ? "static " : isAbstract ? "abstract " : isSealed ? "sealed " : "";
        }
        var members = new List<string[]>();
        var accessors = new HashSet<MethodDefinitionHandle>();

        foreach (var propertyHandle in type.GetProperties())
        {
            var property = reader.GetPropertyDefinition(propertyHandle);
            var used = property.GetAccessors();
            if (!used.Getter.IsNil) accessors.Add(used.Getter);
            if (!used.Setter.IsNil) accessors.Add(used.Setter);
            string getAccess = used.Getter.IsNil ? null : Access(reader.GetMethodDefinition(used.Getter).Attributes);
            string setAccess = used.Setter.IsNil ? null : Access(reader.GetMethodDefinition(used.Setter).Attributes);
            if (getAccess == null && setAccess == null)
                continue;
            if (HasAttribute(reader, property.GetCustomAttributes(), "ObsoleteAttribute"))
                continue;
            var any = reader.GetMethodDefinition(used.Getter.IsNil ? used.Setter : used.Getter);
            var signature = property.DecodeSignature(Provider, context);
            var propertyName = reader.GetString(property.Name);
            string access = getAccess == "public" || setAccess == "public" ? "public" : "protected";
            string body = (getAccess != null ? (getAccess == access ? "get; " : getAccess + " get; ") : "")
                + (setAccess != null ? (setAccess == access ? "set; " : setAccess + " set; ") : "");
            string shown = propertyName;
            if (signature.ParameterTypes.Length > 0)
            {
                var getter = used.Getter.IsNil ? default : reader.GetMethodDefinition(used.Getter);
                shown = "this[" + (used.Getter.IsNil ? string.Join(", ", signature.ParameterTypes)
                    : Parameters(reader, getter, getter.DecodeSignature(Provider, context), false)) + "]";
            }
            members.Add(new[] { propertyName, (isInterface ? "" : access + " ") + Modifiers(any.Attributes, isInterface)
                + signature.ReturnType + " " + shown + " { " + body + "}" });
        }

        foreach (var eventHandle in type.GetEvents())
        {
            var definition = reader.GetEventDefinition(eventHandle);
            var used = definition.GetAccessors();
            if (!used.Adder.IsNil) accessors.Add(used.Adder);
            if (!used.Remover.IsNil) accessors.Add(used.Remover);
            if (!used.Raiser.IsNil) accessors.Add(used.Raiser);
            if (used.Adder.IsNil)
                continue;
            var adder = reader.GetMethodDefinition(used.Adder);
            string access = Access(adder.Attributes);
            if (access == null || HasAttribute(reader, definition.GetCustomAttributes(), "ObsoleteAttribute"))
                continue;
            var eventName = reader.GetString(definition.Name);
            members.Add(new[] { eventName, (isInterface ? "" : access + " ") + Modifiers(adder.Attributes, isInterface) + "event "
                + EntityName(reader, definition.Type, context) + " " + eventName });
        }

        var enumValues = new List<string>();
        foreach (var fieldHandle in type.GetFields())
        {
            var field = reader.GetFieldDefinition(fieldHandle);
            string access = Access(field.Attributes);
            if (access == null || (field.Attributes & FieldAttributes.SpecialName) != 0)
                continue;
            var fieldName = reader.GetString(field.Name);
            if (kind == "enum")
            {
                enumValues.Add(fieldName);
                continue;
            }
            if (HasAttribute(reader, field.GetCustomAttributes(), "ObsoleteAttribute"))
                continue;
            string modifier = (field.Attributes & FieldAttributes.Literal) != 0 ? "const "
                : ((field.Attributes & FieldAttributes.Static) != 0 ? "static " : "")
                  + ((field.Attributes & FieldAttributes.InitOnly) != 0 ? "readonly " : "");
            members.Add(new[] { fieldName, access + " " + modifier + field.DecodeSignature(Provider, context) + " " + fieldName });
        }
        if (kind == "enum")
            members.Add(new[] { "", string.Join(", ", enumValues) });

        foreach (var methodHandle in type.GetMethods())
        {
            if (accessors.Contains(methodHandle))
                continue;
            var method = reader.GetMethodDefinition(methodHandle);
            string access = Access(method.Attributes);
            if (access == null)
                continue;
            var methodName = reader.GetString(method.Name);
            bool constructor = methodName == ".ctor";
            if (kind == "delegate" && methodName != "Invoke")
                continue;
            if (!constructor && ((method.Attributes & MethodAttributes.SpecialName) != 0 || methodName.StartsWith("<")))
                continue;
            if (HasAttribute(reader, method.GetCustomAttributes(), "ObsoleteAttribute"))
                continue;
            var methodContext = new GenericContext { Type = context.Type, Method = GenericNames(reader, method.GetGenericParameters()) };
            var signature = method.DecodeSignature(Provider, methodContext);
            bool extension = (method.Attributes & MethodAttributes.Static) != 0
                && HasAttribute(reader, method.GetCustomAttributes(), "ExtensionAttribute");
            string parameters = Parameters(reader, method, signature, extension);
            string generics = methodContext.Method.Length > 0 ? "<" + string.Join(", ", methodContext.Method) + ">" : "";
            if (kind == "delegate")
                members.Add(new[] { "Invoke", signature.ReturnType + " Invoke(" + parameters + ")" });
            else if (constructor)
                members.Add(new[] { ".ctor", access + " " + name.Substring(name.LastIndexOf('.') + 1) + "(" + parameters + ")" });
            else
                members.Add(new[] { methodName, (isInterface ? "" : access + " ") + Modifiers(method.Attributes, isInterface)
                    + signature.ReturnType + " " + methodName + generics + "(" + parameters + ")" });
        }

        string head = "public " + modifiers + kind + " " + display + (bases.Count > 0 ? " : " + string.Join(", ", bases) : "");
        return new Dictionary<string, object>
        {
            ["ns"] = Namespace(reader, handle), ["n"] = display, ["k"] = kind, ["h"] = head, ["b"] = bases, ["m"] = members,
        };
    }
}
