"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { healthApi } from "@/lib/api";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { PlaidBankConnections } from "./plaid-bank-connections";
import {
  Settings as SettingsIcon,
  Palette,
  Cloud,
  Database,
  Download,
  AlertCircle,
  CheckCircle,
  Info
} from "lucide-react";

export function SettingsPage() {


  // Получаем статус здоровья API
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.check,
    refetchInterval: 30000, // Обновлять каждые 30 секунд
  });


  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">
            Configure your budget management preferences
          </p>
        </div>
        <Badge variant="secondary" className="gap-2">
          <SettingsIcon className="h-4 w-4" />
          v4.0.0
        </Badge>
      </div>

      {/* System Status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Info className="h-5 w-5" />
            System Status
          </CardTitle>
          <CardDescription>
            Current status of application services
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">API Status</span>
              <Badge variant={health?.ok ? "default" : "destructive"}>
                {healthLoading ? "Loading..." : health?.ok ? "Online" : "Offline"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Railway Database</span>
              <Badge variant={health?.ok ? "default" : "secondary"}>
                {healthLoading ? "Loading..." : health?.ok ? "Connected" : "Disconnected"}
              </Badge>
            </div>
          </div>

          {health?.ok && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                Database connection: Active and healthy
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Appearance */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Palette className="h-5 w-5" />
            Appearance
          </CardTitle>
          <CardDescription>
            Customize the look and feel of the application
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Theme</Label>
              <p className="text-sm text-muted-foreground">
                Toggle between light and dark mode
              </p>
            </div>
            <ThemeToggle />
          </div>

        </CardContent>
      </Card>

      {/* Database Status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cloud className="h-5 w-5" />
            Database Status
          </CardTitle>
          <CardDescription>
            Monitor Railway database connection and health
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Database Connection</Label>
              <p className="text-sm text-muted-foreground">
                Real-time connection status to Railway PostgreSQL
              </p>
            </div>
            <Badge variant={health?.ok ? "default" : "destructive"}>
              {healthLoading ? "Checking..." : health?.ok ? "Connected" : "Disconnected"}
            </Badge>
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Last Health Check</Label>
              <p className="text-sm text-muted-foreground">
                When the database was last checked for connectivity
              </p>
            </div>
            <span className="text-sm text-muted-foreground">
              {healthLoading ? "Checking..." : "Every 30 seconds"}
            </span>
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="text-base">Database Provider</Label>
                <p className="text-sm text-muted-foreground">
                  Railway PostgreSQL cloud database
                </p>
              </div>
              <Badge variant="outline">Railway</Badge>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="text-base">Data Persistence</Label>
                <p className="text-sm text-muted-foreground">
                  All data is automatically backed up and persistent
                </p>
              </div>
              <Badge variant="default">Automatic</Badge>
            </div>
          </div>

          {!health?.ok && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Database connection failed. Please check your Railway configuration and try again.
              </AlertDescription>
            </Alert>
          )}

          {health?.ok && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                Database is healthy and all operations are working normally.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Bank Connections (Plaid) */}
      <PlaidBankConnections />

      {/* Data Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Data Management
          </CardTitle>
          <CardDescription>
            Backup and manage your budget data
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Backup Data</Label>
              <p className="text-sm text-muted-foreground">
                Create a backup of your current data
              </p>
            </div>
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
          </div>

          <Separator />

          <div className="space-y-2">
            <Label className="text-base">Danger Zone</Label>
            <p className="text-sm text-muted-foreground">
              These actions cannot be undone
            </p>
            <div className="flex gap-2">
              <Button variant="destructive" size="sm">
                Clear All Data
              </Button>
              <Button variant="destructive" size="sm">
                Reset Settings
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>


    </div>
  );
}
