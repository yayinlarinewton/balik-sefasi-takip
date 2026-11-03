# Balık Sefası — ücretsiz iptal / yer açılma takip taslağı

## Takip kapsamı
- **Tekneler:** Balık Sefası, Deniz Anası, Aslan, E. Terzioğlu, Armada Grande.
- **Tarihler:** 6 ve 7 Kasım 2026.
- **Sefer:** Ekipmansız Tur, 19.00–01.00 (ertesi gün).
- **Kontrol:** GitHub Actions, her 5 dakikada bir **planlanır** (GitHub geciktirebilir/atlayabilir).
- **Bildirim:** Telegram botu ile; otomatik rezervasyon veya ödeme **yapmaz**.
- **Bitiş:** 7 Kasım 2026 saat 18.55 (İstanbul).

### ÖNEMLİ: Henüz gerçek site üzerinde test edilmedi
Bu paket bir **kurulum/test başlangıcıdır, aktif ve doğrulanmış takip hizmeti değildir.**
Site, kullanıcı seçimlerini JavaScript ile yönetiyor olabilir; dolayısıyla `monitor.py` içindeki
tekne → tur → tarih → sefer adımları sitenin gerçek HTML/DOM'una göre uyarlanmalıdır.
Mevcut kod **belirsiz sonuçlarda bildirim üretmez** ve `diagnostics/` klasörüne ekran
görüntüsü ve görünen kontrolleri kaydeder. İlk eylemi manuel çalıştırıp tanılama çıktıları
incelenmeden bildirimlerin çalıştığı kabul edilmemelidir.

## GitHub'a kurulum
1. GitHub hesabınızda yeni bir **public** depo oluşturun: standart Actions çalıştırmaları ücretsizdir. **Dikkat:** Depodaki kod, izlenen tekne ve tarihler herkese görünür. Bunları gizli tutmak isterseniz **private** depo oluşturabilirsiniz fakat aylık ücretsiz çalışma kotasını aşma riski vardır. Token/Chat ID yalnızca **Secrets** alanında saklanmalıdır.
2. Bu ZIP içindeki dosyaları, `.github/workflows/check-availability.yml` dahil, depoya yükleyin.
   - ZIP arşivini doğrudan yüklemek yerine çıkarıp tüm dosyaları yükleyin.
   - `.github` gizli klasör olduğu için görünmezse GitHub web arayüzünde kendiniz oluşturun.
3. Depo **Settings → Actions → General → Workflow permissions** kısmında
   `Read and write permissions` seçeneğini etkinleştirin (state.json durum kaydı için).
4. Telegram'da `@BotFather` hesabına `/newbot` gönderip bir bot oluşturun.
   - Bot erişim anahtarını kimseye göndermeyin, herkese açık yere yazmayın.
   - Oluşturduğunuz botla sohbet açıp `/start` gönderin.
   - `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates` yanıtında `message.chat.id` değerini bulun.
   - Bu adresi tarayıcı geçmişine kaydetmemeye dikkat edin; anahtarı sonradan yenileyebilirsiniz.
5. GitHub **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN`: BotFather token'ı
   - `TELEGRAM_CHAT_ID`: kendi chat ID'niz
6. **Actions → Balik Sefasi - Iptal Takibi → Run workflow** ile ilk manuel testi yapın.
7. Çalışmanın altındaki **Artifacts** bölümünden `balik-sefasi-diagnostics-...` arşivini indirin.
8. Tanılama görüntülerinde site seçimleri çalışmadıysa bot henüz hazır değildir. Tanılama arşivleri yalnızca **manuel çalıştırmada** yüklenir; 5 dakikalık otomatik çalıştırmalarda depolama tüketimini azaltmak için arşiv yüklenmez.
   Görüntüleri (kişisel bilgi varsa silerek) ChatGPT'ye yükleyin; siteye uygun seçiciler düzeltilebilir.
9. Gerçek bir dolu sefer ve müsait seferle çalıştığını doğruladıktan sonra otomatik takip anlamlıdır.

## Hata önleme
- `UNKNOWN` durumu, müsaitlik anlamına gelmez; bu durumda bildirim gönderilmez.
- Sayfa genelinde 'Müsait' kelimesinin bulunması yeterli görülmez; **seçilen saate ait** kayıt aranır.
- Sadece `DOLU` yerine `MÜSAİT` veya `AZ YER` tespit edilirse haber verilir.
- Başlangıçta müsait olan sefer bulunursa da haber gönderilebilir.
- `state.json` yalnızca durum değişince yazılır, tekrarlayan bildirimler azaltılır.
- Site robot trafiğini engellerse, captcha sunarsa veya DOM değişirse bu sistem bunu aşmaya çalışmaz.

## Plan sınırları
GitHub Actions'ın minimum zamanlama aralığı 5 dakikadır ama gerçek başlatma zamanı
garanti değildir; gecikme veya bazı çalıştırmaların atlanması mümkündür.
Ücretsiz özel depo için aylık Actions dakika kotası geçerlidir. Her kontrolün 10 farklı
sayfa/akışa girmesi, Playwright'ın başlatılması ve Chromium indirilmesi dakika tüketebilir.
Bu kısa süreli izleme için yeterli kalması olasıdır ama kullanım göstergesi takip edilmelidir.
Her 5 dakikada tüm seçenekleri kontrol etmek siteye yük getirebilir. Site kullanımı
koşulları ve olası hız sınırlamaları gözetilmelidir.

## Teknik bilgiler
- Python 3.12
- Playwright Chromium
- GitHub Actions planlama: `2-57/5 * * * *` (UTC)
- Telegram Bot API
- API anahtarları yalnızca GitHub Actions secrets'ta olmalı.
