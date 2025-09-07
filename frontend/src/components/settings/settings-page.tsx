"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { healthApi, syncApi } from "@/lib/api";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import {
  Settings as SettingsIcon,
  Palette,
  Cloud,
  Database,
  Shield,
  Bell,
  Download,
  Upload,
  AlertCircle,
  CheckCircle,
  Info
} from "lucide-react";

export function SettingsPage() {
  const [notifications, setNotifications] = useState(true);
  const [autoSync, setAutoSync] = useState(true);
  const [syncFrequency, setSyncFrequency] = useState("5");
  const [currency, setCurrency] = useState("USD");

  const queryClient = useQueryClient();

  // Получаем статус здоровья API
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.checkHealth,
    refetchInterval: 30000, // Обновлять каждые 30 секунд
  });

  // Получаем статус синхронизации
  const { data: syncStatus, isLoading: syncLoading } = useQuery({
    queryKey: ["sync-status"],
    queryFn: syncApi.getStatus,
  });

  // Мутация для ручной синхронизации
  const pullMutation = useMutation({
    mutationFn: syncApi.pull,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["report"] });
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
    },
  });

  const pushMutation = useMutation({
    mutationFn: syncApi.push,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
  });

  const handlePull = () => {
    pullMutation.mutate();
  };

  const handlePush = () => {
    pushMutation.mutate();
  };

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
              <span className="text-sm font-medium">GitHub Sync</span>
              <Badge variant={syncStatus?.configured ? "default" : "secondary"}>
                {syncLoading ? "Loading..." : syncStatus?.configured ? "Configured" : "Not Configured"}
              </Badge>
            </div>
          </div>

          {syncStatus?.last_sync && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                Last sync: {new Date(syncStatus.last_sync).toLocaleString()}
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

          <Separator />

          <div className="space-y-2">
            <Label htmlFor="currency">Currency</Label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="USD">USD ($)</SelectItem>
                <SelectItem value="EUR">EUR (€)</SelectItem>
                <SelectItem value="RUB">RUB (₽)</SelectItem>
                <SelectItem value="GBP">GBP (£)</SelectItem>
                <SelectItem value="JPY">JPY (¥)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Synchronization */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cloud className="h-5 w-5" />
            Synchronization
          </CardTitle>
          <CardDescription>
            Manage data synchronization with GitHub
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Auto Sync</Label>
              <p className="text-sm text-muted-foreground">
                Automatically sync data in background
              </p>
            </div>
            <Switch checked={autoSync} onCheckedChange={setAutoSync} />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sync-frequency">Sync Frequency (minutes)</Label>
            <Select value={syncFrequency} onValueChange={setSyncFrequency}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Every minute</SelectItem>
                <SelectItem value="5">Every 5 minutes</SelectItem>
                <SelectItem value="15">Every 15 minutes</SelectItem>
                <SelectItem value="30">Every 30 minutes</SelectItem>
                <SelectItem value="60">Every hour</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Separator />

          <div className="flex gap-2">
            <Button
              onClick={handlePull}
              disabled={!syncStatus?.configured || pullMutation.isPending}
              variant="outline"
              className="flex-1"
            >
              <Download className="h-4 w-4 mr-2" />
              {pullMutation.isPending ? "Pulling..." : "Pull from GitHub"}
            </Button>
            <Button
              onClick={handlePush}
              disabled={!syncStatus?.configured || pushMutation.isPending}
              variant="outline"
              className="flex-1"
            >
              <Upload className="h-4 w-4 mr-2" />
              {pushMutation.isPending ? "Pushing..." : "Push to GitHub"}
            </Button>
          </div>

          {pullMutation.isError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Failed to pull data: {pullMutation.error?.message}
              </AlertDescription>
            </Alert>
          )}

          {pushMutation.isError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Failed to push data: {pushMutation.error?.message}
              </AlertDescription>
            </Alert>
          )}

          {!syncStatus?.configured && (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                GitHub synchronization is not configured. Set up GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO in your environment variables.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

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

      {/* Notifications */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            Notifications
          </CardTitle>
          <CardDescription>
            Configure notification preferences
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Budget Alerts</Label>
              <p className="text-sm text-muted-foreground">
                Get notified when approaching budget limits
              </p>
            </div>
            <Switch checked={notifications} onCheckedChange={setNotifications} />
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Sync Notifications</Label>
              <p className="text-sm text-muted-foreground">
                Get notified about sync status changes
              </p>
            </div>
            <Switch checked={true} />
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Security
          </CardTitle>
          <CardDescription>
            Manage security and access settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="admin-key">Admin Key</Label>
            <Input
              id="admin-key"
              type="password"
              placeholder="Enter admin key"
              className="max-w-sm"
            />
            <p className="text-sm text-muted-foreground">
              Required for administrative operations
            </p>
          </div>

          <Separator />

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Session Timeout</Label>
              <p className="text-sm text-muted-foreground">
                Automatically log out after period of inactivity
              </p>
            </div>
            <Select defaultValue="30">
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="15">15 minutes</SelectItem>
                <SelectItem value="30">30 minutes</SelectItem>
                <SelectItem value="60">1 hour</SelectItem>
                <SelectItem value="120">2 hours</SelectItem>
                <SelectItem value="never">Never</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
