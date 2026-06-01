import NextAuth, { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "Django Credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" }
      },
      async authorize(credentials) {
        if (!credentials?.username || !credentials?.password) return null;

        try {
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost/api";
          // If we are calling from the server inside the docker container network, 
          // we use BACKEND_API_URL (like http://backend:8000/api) for server-side auth requests.
          const backendUrl = process.env.BACKEND_API_URL || apiUrl;
          
          const res = await fetch(`${backendUrl}/token/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              username: credentials.username,
              password: credentials.password
            })
          });

          if (!res.ok) return null;
          const tokens = await res.json(); // returns { access, refresh }

          // We return user object containing tokens
          return {
            id: credentials.username,
            name: credentials.username,
            accessToken: tokens.access,
            refreshToken: tokens.refresh,
          };
        } catch (error) {
          console.error("Auth authorize error:", error);
          return null;
        }
      }
    })
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = user.accessToken;
        token.refreshToken = user.refreshToken;
        token.username = user.name;
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken;
      session.refreshToken = token.refreshToken;
      session.username = token.username;
      return session;
    }
  },
  pages: {
    signIn: "/",
  },
  session: {
    strategy: "jwt",
  },
  secret: process.env.NEXTAUTH_SECRET,
};

const handler = NextAuth(authOptions);
export { handler as GET, handler as POST };
