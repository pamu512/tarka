import "axios";

declare module "axios" {
  export interface AxiosRequestConfig {
    /**
     * When true, the 401 refresh interceptor will not run (prevents loops on auth endpoints).
     */
    skipAuthRefresh?: boolean;
  }
}
