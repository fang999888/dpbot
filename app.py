def send_daily_push():
    """發送每日推播給所有訂閱用戶（含除錯日誌）"""
    if not supabase:
        print("❌ Supabase 未連線，無法推播")
        return

    today = datetime.now(timezone.utc).date().isoformat()
    print(f"🔍 今天的日期 (UTC): {today}")

    try:
        # 查詢所有 is_active = true 且 last_push_date != today 的用戶
        print("🔍 執行查詢: is_active=True, last_push_date != today")
        response = supabase.table('subscribers')\
            .select('*')\
            .eq('is_active', True)\
            .neq('last_push_date', today)\
            .execute()
        
        subscribers = response.data
        print(f"🔍 查詢結果: {subscribers}")  # 印出原始回傳資料

        if not subscribers:
            print("📭 今天沒有需要推播的用戶（查詢結果為空）")
            return

        # 逐一處理每個訂閱者
        daily_fact = get_daily_plant_fact()
        print(f"🌱 今日知識: {daily_fact}")

        success_count = 0
        for sub in subscribers:
            user_id = sub['user_id']
            last_push = sub.get('last_push_date')
            print(f"👉 準備推播給 {user_id} (last_push_date={last_push})")

            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=f"🌱 **蕨積早安**\n\n{daily_fact}")
                )
                # 更新 last_push_date 為今天
                update_result = supabase.table('subscribers')\
                    .update({'last_push_date': today})\
                    .eq('user_id', user_id)\
                    .execute()
                print(f"✅ 推播成功，已更新 last_push_date: {update_result.data}")
                success_count += 1
            except Exception as e:
                print(f"❌ 推播失敗 {user_id}: {e}")

        print(f"📊 推播完成：成功 {success_count} / 總共 {len(subscribers)}")
    except Exception as e:
        print(f"❌ 推播處理時發生例外: {e}")
