// GENERATED FILE - do not edit by hand.
// Source: backend pydantic models -> OpenAPI -> openapi-typescript.
// Regenerate with `npm run gen:api` after changing backend/app/schemas.py or a route.

export interface paths {
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Models */
        get: operations["list_models_api_models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/presets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Presets */
        get: operations["list_presets_api_presets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/presets/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Save Preset */
        put: operations["save_preset_api_presets__name__put"];
        post?: never;
        /** Delete Preset */
        delete: operations["delete_preset_api_presets__name__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/flags": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Flag Schema */
        get: operations["get_flag_schema_api_server_flags_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/restart": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restart Server
         * @description Apply new flags to the running server. Restarts immediately if it's
         *     idle; if llama-server reports an in-flight generation (via /slots), the
         *     restart is queued and applied automatically as soon as it finishes.
         */
        post: operations["restart_server_api_server_restart_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/restart/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Restart */
        post: operations["cancel_restart_api_server_restart_cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Server */
        post: operations["start_server_api_server_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Status */
        get: operations["get_status_api_server_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/server/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stop Server */
        post: operations["stop_server_api_server_stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** DeletedResponse */
        DeletedResponse: {
            /** Deleted */
            deleted: string;
        };
        /** FlagDef */
        FlagDef: {
            /** Cli */
            cli: string;
            /** Default */
            default: boolean | number | string | null;
            /**
             * Group
             * @enum {string}
             */
            group: "basic" | "advanced";
            /** Help */
            help: string | null;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Options */
            options: string[] | null;
            /**
             * Type
             * @enum {string}
             */
            type: "boolean" | "number" | "string" | "enum" | "path";
        };
        /** HealthResponse */
        HealthResponse: {
            /**
             * Status
             * @constant
             */
            status: "ok";
            /** Version */
            version: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** ModelInfo */
        ModelInfo: {
            /** Architecture */
            architecture: string | null;
            /** Context Length */
            context_length: number | null;
            /** Display Name */
            display_name: string;
            /** Entry Path */
            entry_path: string;
            /** File Type */
            file_type: string | null;
            /** Id */
            id: string;
            /**
             * Is Split
             * @default false
             */
            is_split: boolean;
            /** Parts */
            parts: components["schemas"]["ModelPart"][];
            /** Total Size Bytes */
            total_size_bytes: number;
        };
        /** ModelPart */
        ModelPart: {
            /** Filename */
            filename: string;
            /** Path */
            path: string;
            /** Size Bytes */
            size_bytes: number;
        };
        /** Preset */
        Preset: {
            /**
             * Flags
             * @default {}
             */
            flags: {
                [key: string]: boolean | number | string | null;
            };
            /** Model Id */
            model_id: string;
            /** Name */
            name: string;
        };
        /** RestartResponse */
        RestartResponse: {
            /**
             * Result
             * @enum {string}
             */
            result: "applied" | "queued";
            status: components["schemas"]["StatusResponse"];
        };
        /** StartRequest */
        StartRequest: {
            /**
             * Flags
             * @default {}
             */
            flags: {
                [key: string]: boolean | number | string | null;
            };
            /** Model Id */
            model_id: string;
        };
        /** StatusResponse */
        StatusResponse: {
            /**
             * Adopted
             * @default false
             */
            adopted: boolean;
            /** Args */
            args: string[] | null;
            /** Busy */
            busy: boolean | null;
            /** Exit Code */
            exit_code: number | null;
            /** Flags */
            flags: {
                [key: string]: boolean | number | string | null;
            } | null;
            /** Model Id */
            model_id: string | null;
            /** Pid */
            pid: number | null;
            /**
             * Restart Pending
             * @default false
             */
            restart_pending: boolean;
            /** Started At */
            started_at: number | null;
            /**
             * State
             * @enum {string}
             */
            state: "stopped" | "starting" | "running" | "stopping" | "crashed";
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    list_models_api_models_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelInfo"][];
                };
            };
        };
    };
    list_presets_api_presets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Preset"][];
                };
            };
        };
    };
    save_preset_api_presets__name__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Preset"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Preset"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_preset_api_presets__name__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeletedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_flag_schema_api_server_flags_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FlagDef"][];
                };
            };
        };
    };
    restart_server_api_server_restart_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StartRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RestartResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_restart_api_server_restart_cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
        };
    };
    start_server_api_server_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StartRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_status_api_server_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
        };
    };
    stop_server_api_server_stop_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
        };
    };
}
