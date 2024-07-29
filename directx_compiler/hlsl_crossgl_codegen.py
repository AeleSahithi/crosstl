from .ast import *
from .parser import *
from .lexer import *


class HLSLToCrossGLConverter:
    def __init__(self):
        self.vertex_inputs = []
        self.vertex_outputs = []
        self.fragment_inputs = []
        self.fragment_outputs = []
        self.type_map = {
            "float": "float",
            "float2": "vec2",
            "float3": "vec3",
            "float4": "vec4",
            "int": "int",
        }

    def convert(self, ast):
        self.process_structs(ast)
        self.process_function_params(ast)

        code = "shader main {\n"

        # Generate custom functions
        for func in ast.functions:
            if func.name not in ["VSMain", "PSMain"]:
                code += self.generate_function(func)

        # Generate vertex shader
        code += "vertex {\n"
        code += self.generate_io_declarations("vertex")
        code += self.generate_vertex_main(
            next(f for f in ast.functions if f.name == "VSMain")
        )
        code += "}\n"

        # Generate fragment shader
        code += "fragment {\n"
        code += self.generate_io_declarations("fragment")
        code += self.generate_fragment_main(
            next(f for f in ast.functions if f.name == "PSMain")
        )
        code += "}\n"

        code += "}\n"
        return code

    def process_structs(self, ast):
        if ast.input_struct and ast.input_struct.name == "VS_INPUT":
            for member in ast.input_struct.members:
                self.vertex_inputs.append((member.vtype, member.name, member.semantic))
        if ast.output_struct and ast.output_struct.name == "VS_OUTPUT":
            for member in ast.output_struct.members:
                if member.semantic == ": SV_POSITION":
                    continue  # Skip SV_POSITION as it's handled by gl_Position
                self.vertex_outputs.append((member.vtype, member.name, member.semantic))
                self.fragment_inputs.append(
                    (member.vtype, member.name, member.semantic)
                )

    def process_function_params(self, ast):
        for func in ast.functions:
            if func.name == "VSMain":
                if not self.vertex_inputs:  # Only process if not already set by struct
                    self.vertex_inputs = [
                        (p.vtype, p.name, p.semantic) for p in func.params
                    ]
            elif func.name == "PSMain":
                if len(func.params) == 1 and func.params[0].vtype == "PSInput":
                    # PSInput struct is used, so fragment_inputs is already set
                    pass
                else:
                    self.fragment_inputs = [
                        (p.vtype, p.name, p.semantic) for p in func.params
                    ]

    def generate_io_declarations(self, shader_type):
        code = ""
        if shader_type == "vertex":
            for type, name, semantic in self.vertex_inputs:
                code += f"input {self.map_type(type)} {name}; // {semantic}\n"
            for type, name, semantic in self.vertex_outputs:
                code += f"output {self.map_type(type)} {name}; // {semantic}\n"
        elif shader_type == "fragment":
            for type, name, semantic in self.fragment_inputs:
                code += f"input {self.map_type(type)} {name}; // {semantic}\n"
            for type, name, semantic in self.fragment_outputs:
                code += f"output {self.map_type(type)} {name}; // {semantic}\n"
        return code

    def generate_function(self, func):
        params = ", ".join(f"{self.map_type(p.vtype)} {p.name}" for p in func.params)
        code = f"{self.map_type(func.return_type)} {func.name}({params}) {{\n"
        code += self.generate_function_body(func.body, indent=1)
        code += "}\n\n"
        return code

    def generate_vertex_main(self, func):
        print(func.return_type)
        return_type = func.return_type
        if return_type in self.type_map.keys():
            return_type = map_type[return_type]
            params = ", ".join(
                f"{self.map_type(p.vtype)} {p.name}" for p in func.params
            )
            code = f"{return_type} main({params}) {{\n"
        else:
            code = f"void main() {{\n"
            code += self.generate_function_body(func.body, indent=1, is_main=True)
        code += "}\n"
        return code

    def generate_fragment_main(self, func):
        if len(func.params) == 1 and func.params[0].vtype == "PSInput":
            # If using PSInput struct, don't include parameters in main()
            code = "void main() {\n"
        else:
            params = ", ".join(
                f"{self.map_type(p.vtype)} {p.name}" for p in func.params
            )
            code = f"void main({params}) {{\n"
        code += self.generate_function_body(func.body, indent=1, is_main=True)
        code += "}\n"
        return code

    def generate_function_body(self, body, indent=0, is_main=False):
        code = ""
        for stmt in body:
            code += "    " * indent
            if isinstance(stmt, VariableNode):
                if not is_main:
                    code += f"{self.map_type(stmt.vtype)} {stmt.name};\n"
            elif isinstance(stmt, AssignmentNode):
                code += self.generate_assignment(stmt, is_main) + ";\n"
            elif isinstance(stmt, IfNode):
                code += self.generate_if(stmt, indent, is_main)
            elif isinstance(stmt, ForNode):
                code += self.generate_for(stmt, indent, is_main)
            elif isinstance(stmt, ReturnNode):
                if is_main:
                    # Skip return statements in main functions
                    continue
                code += f"return {self.generate_expression(stmt.value, is_main)};\n"
        return code

    def generate_assignment(self, node, is_main):
        lhs = self.generate_expression(node.left, is_main)
        rhs = self.generate_expression(node.right, is_main)
        return f"{lhs} = {rhs}"

    def generate_if(self, node, indent, is_main):
        code = f"if ({self.generate_expression(node.condition, is_main)}) {{\n"
        code += self.generate_function_body(node.if_body, indent + 1, is_main)
        code += "    " * indent + "}"
        if node.else_body:
            code += " else {\n"
            code += self.generate_function_body(node.else_body, indent + 1, is_main)
            code += "    " * indent + "}"
        code += "\n"
        return code

    def generate_for(self, node, indent, is_main):
        init = self.generate_statement(node.init, is_main).rstrip(";")
        condition = self.generate_expression(node.condition, is_main)
        update = self.generate_statement(node.update, is_main).rstrip(";")
        code = f"for ({init}; {condition}; {update}) {{\n"
        code += self.generate_function_body(node.body, indent + 1, is_main)
        code += "    " * indent + "}\n"
        return code

    def generate_expression(self, expr, is_main=False):
        if isinstance(expr, str):
            return expr
        elif isinstance(expr, VariableNode):
            return expr.name
        elif isinstance(expr, BinaryOpNode):
            left = self.generate_expression(expr.left, is_main)
            right = self.generate_expression(expr.right, is_main)
            return f"({left} {expr.op} {right})"
        elif isinstance(expr, UnaryOpNode):
            operand = self.generate_expression(expr.operand, is_main)
            return f"({expr.operator}{operand})"
        elif isinstance(expr, FunctionCallNode):
            args = ", ".join(
                self.generate_expression(arg, is_main) for arg in expr.args
            )
            return f"{expr.name}({args})"
        elif isinstance(expr, MemberAccessNode):
            obj = self.generate_expression(expr.object)
            if obj == "output" or obj == "input":
                return f"{expr.member}"
            return f"{obj}.{expr.member}"
        elif isinstance(expr, VectorConstructorNode):
            args = ", ".join(
                self.generate_expression(arg, is_main) for arg in expr.args
            )
            return f"{self.map_type(expr.type_name)}({args})"
        else:
            return str(expr)

    def generate_statement(self, stmt, is_main):
        if isinstance(stmt, AssignmentNode):
            return self.generate_assignment(stmt, is_main) + ";"
        elif isinstance(stmt, VariableNode):
            if hasattr(stmt, "semantic") and stmt.semantic is not None:
                return f"{self.map_type(stmt.vtype)} {stmt.name} = {stmt.semantic};"
            else:
                return f"{self.map_type(stmt.vtype)} {stmt.name};"
        else:
            return self.generate_expression(stmt, is_main) + ";"

    def map_type(self, hlsl_type):

        return self.type_map.get(hlsl_type, hlsl_type)


# Usage
if __name__ == "__main__":
    code = """
    // This is a single-line comment
    /* This is a
       multi-line comment */
    struct VS_INPUT {
        float3 position : POSITION;
        float2 texCoord : TEXCOORD0;
    };

    float4 calculateNormal(float3 position, float3 normal)
        {
            float4 result = float4(normal, 1.0);
            return result;
        }
    
    struct VS_OUTPUT {
        float4 position : SV_POSITION;
        float2 texCoord : TEXCOORD0;
    };

    VS_OUTPUT VSMain(VS_INPUT input)
    {
        VS_OUTPUT output;
        output.texCoord = input.texCoord;
        for (int i = 0; i < 10; i=i+1){
            output.position = float4(input.position, 1.0);
        }
        
        if (output.position.x > 0.0) {
            output.position.y = 0.0;
        } else {
            output.position.y = 1.0;
        }
        
        output.position = float4(input.position, 1.0);
        return output;
    }
    
    struct PS_OUTPUT {
        float4 color : SV_TARGET;
    };
    
    PS_OUTPUT PSMain(VS_OUTPUT input) : SV_TARGET
    {
        PS_OUTPUT output;
        output.color = float4(1.0, 0.0, 0.0, 1.0);
        return output;
    }
    
    
    
    """

    lexer = HLSLLexer(code)
    parser = HLSLParser(lexer.tokens)
    ast = parser.parse()
    print("Parsing completed successfully!")
    print(ast)
    codegen = HLSLToCrossGLConverter()
    hlsl_code = codegen.convert(ast)
    print(hlsl_code)
